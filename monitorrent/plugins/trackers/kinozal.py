#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import re
import six
import pytz
import datetime
from requests import Session
import requests
from sqlalchemy import Column, Integer, String, ForeignKey, MetaData, Table, text
from monitorrent.db import Base, DBSession, UTCDateTime
from monitorrent.plugins import Topic
from monitorrent.plugin_managers import register_plugin
from monitorrent.utils.soup import get_soup
from monitorrent.plugins.trackers import TrackerPluginBase, WithCredentialsMixin, ExecuteWithHashChangeMixin, LoginResult

PLUGIN_NAME = 'kinozal.guru'
KINOZAL_HOST = 'kinozal.guru'
LEGACY_PLUGIN_NAME = 'kinozal.tv'
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', '')


class KinozalCredentials(Base):
    __tablename__ = "kinozal_credentials"

    username = Column(String, primary_key=True)
    password = Column(String, primary_key=True)
    c_uid = Column(String, nullable=True)
    c_pass = Column(String, nullable=True)
    cf_clearance = Column(String, nullable=True)
    cf_user_agent = Column(String, nullable=True)


class KinozalTopic(Topic):
    __tablename__ = "kinozal_topics"

    id = Column(Integer, ForeignKey('topics.id'), primary_key=True)
    hash = Column(String, nullable=True)
    last_torrent_update = Column(UTCDateTime, nullable=True)

    __mapper_args__ = {
        'polymorphic_identity': PLUGIN_NAME
    }


# noinspection PyUnusedLocal
def upgrade(engine, operations_factory):
    if not engine.dialect.has_table(engine.connect(), KinozalTopic.__tablename__):
        return
    version = get_current_version(engine)
    if version == 0:
        with operations_factory() as operations:
            # remove capital later
            operations.rename_table('Kinozal_topics', 'kinozal_topics1')
            operations.rename_table('kinozal_topics1', KinozalTopic.__tablename__)

            operations.rename_table('Kinozal_credentials', 'kinozal_credentials1')
            operations.rename_table('kinozal_credentials1', KinozalCredentials.__tablename__)

            last_torrent_update = Column('last_torrent_update', UTCDateTime, nullable=True)
            operations.add_column(KinozalTopic.__tablename__, last_torrent_update)
        version = 1

    # Cloudflare cookie cache columns
    m = MetaData(engine)
    credentials = Table(KinozalCredentials.__tablename__, m, autoload=True)
    with operations_factory() as operations:
        if 'cf_clearance' not in credentials.columns:
            operations.add_column(KinozalCredentials.__tablename__,
                                  Column('cf_clearance', String, nullable=True))
        if 'cf_user_agent' not in credentials.columns:
            operations.add_column(KinozalCredentials.__tablename__,
                                  Column('cf_user_agent', String, nullable=True))

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE topics SET type = :new WHERE type = :old"),
            {"new": PLUGIN_NAME, "old": LEGACY_PLUGIN_NAME},
        )
        conn.execute(
            text("UPDATE topics SET url = REPLACE(url, :old_host, :new_host) WHERE url LIKE :pattern"),
            {"old_host": LEGACY_PLUGIN_NAME, "new_host": KINOZAL_HOST, "pattern": "%kinozal.tv%"},
        )


def get_current_version(engine):
    m = MetaData(engine)
    topics = Table(KinozalTopic.__tablename__, m, autoload=True)
    if 'last_torrent_update' not in topics.columns:
        return 0
    return 1


class KinozalDateParser(object):
    months = {
        u'января': 1,
        u'февраля': 2,
        u'марта': 3,
        u'апреля': 4,
        u'мая': 5,
        u'июня': 6,
        u'июля': 7,
        u'августа': 8,
        u'сентября': 9,
        u'октября': 10,
        u'ноября': 11,
        u'декабря': 12,
    }
    relative_days = {
        u'сегодня': 0,
        u'вчера': -1
    }
    now_text = u'сейчас'
    tz_moscow = pytz.timezone(u'Europe/Moscow')

    def __init__(self):
        months = u'|'.join(self.months)
        relative_days = u'(?P<relative>{0}|{1})'.format(*self.relative_days.keys())
        time_pattern = u'(?P<hours>\d{1,2}):(?P<minutes>\d{1,2})'
        date_pattern = u'(?P<day>\d{1,2})\s+(?P<month>' + months + u')\s+(?P<year>\d{4})'
        pattern = u'^({0}|{1})\s+в\s+{2}$'.format(date_pattern, relative_days, time_pattern)
        self.time_parse_re = re.compile(pattern, re.UNICODE | re.IGNORECASE)

    def parse(self, date_string):
        if self.now_text in date_string:
            return datetime.datetime.now(pytz.utc)

        match = self.time_parse_re.match(date_string)
        if not match:
            raise Exception(u"Can't parse string: {0}".format(date_string))

        parts = match.groupdict()
        if 'relative' in parts and parts['relative'] is not None:
            delta = datetime.timedelta(days=self.relative_days[parts['relative']])
            date = self.tz_moscow.normalize(datetime.datetime.now(pytz.utc) + delta).date()
        else:
            date = datetime.date(int(parts['year']), self.months[parts['month']], int(parts['day']))

        parsed_date_time = datetime.datetime(date.year, date.month, date.day, int(parts['hours']),
                                             int(parts['minutes']))

        return self.tz_moscow.localize(parsed_date_time)


class KinozalLoginFailedException(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


class KinozalTracker(object):
    tracker_settings = None
    login_url = "https://kinozal.guru/takelogin.php"
    profile_page = "https://kinozal.guru/inbox.php"
    url_regex = re.compile(
        six.text_type(r'^\s*https?://(?:www\.)?kinozal\.(?:tv|guru)/details\.php\?id=(\d+)/?\s*$'),
        re.IGNORECASE
    )
    date_parser = KinozalDateParser()

    def __init__(self, c_uid=None, c_pass=None, cf_clearance=None, cf_user_agent=None,
                 cf_cache_updater=None):
        self.c_uid = c_uid
        self.c_pass = c_pass
        self.cf_clearance = cf_clearance
        self.cf_user_agent = cf_user_agent
        self.cf_cache_updater = cf_cache_updater or (lambda clearance, ua: None)

    def setup(self, c_uid, c_pass, cf_clearance=None, cf_user_agent=None):
        self.c_uid = c_uid
        self.c_pass = c_pass
        if cf_clearance is not None:
            self.cf_clearance = cf_clearance
        if cf_user_agent is not None:
            self.cf_user_agent = cf_user_agent

    def _normalize_url(self, url):
        match = self.url_regex.match(url or '')
        if match is None:
            return url
        return "https://{0}/details.php?id={1}".format(KINOZAL_HOST, match.group(1))

    def can_parse_url(self, url):
        return self.url_regex.match(url or '') is not None

    @staticmethod
    def _is_cloudflare_challenge(html, status_code=None):
        # 520/521/522/523 are Cloudflare edge errors that often need a fresh session
        if status_code in (403, 503, 520, 521, 522, 523, 524):
            return True
        if not html:
            return False
        lowered = html.lower()
        return ('just a moment' in lowered) or ('cf-challenge' in lowered) or \
               ('challenge-platform' in lowered) or ('cdn-cgi/challenge' in lowered)

    def _request_kwargs(self):
        kwargs = {}
        if self.tracker_settings:
            kwargs = dict(self.tracker_settings.get_requests_kwargs() or {})
        headers = dict(kwargs.pop('headers', None) or {})
        if self.cf_user_agent:
            headers['User-Agent'] = self.cf_user_agent
        if headers:
            kwargs['headers'] = headers
        kwargs.setdefault('timeout', 15)
        return kwargs

    def _merge_cookies(self, cookies=None):
        merged = {}
        auth = self.get_cookies()
        if auth:
            merged.update(auth)
        if self.cf_clearance:
            merged['cf_clearance'] = self.cf_clearance
        if cookies:
            merged.update(cookies)
        return merged or None

    def _store_cf_cache(self, clearance, user_agent):
        if clearance:
            self.cf_clearance = clearance
        if user_agent:
            self.cf_user_agent = user_agent
        try:
            self.cf_cache_updater(self.cf_clearance, self.cf_user_agent)
        except Exception:
            pass

    def _fetch_html(self, url, cookies=None, allow_redirects=True, use_flaresolverr=True):
        merged = self._merge_cookies(cookies)
        kwargs = self._request_kwargs()
        response = None
        try:
            response = requests.get(
                url,
                cookies=merged,
                allow_redirects=allow_redirects,
                **kwargs
            )
            if response.status_code not in (301, 302, 303, 307, 308) and \
                    not self._is_cloudflare_challenge(response.text, response.status_code):
                return response.text, response.status_code
        except Exception:
            response = None

        if use_flaresolverr:
            html = self._fetch_via_flaresolverr(url, cookies=merged)
            if html is not None:
                # Retry once with freshly cached CF cookies — usually much faster next times.
                if self.cf_clearance:
                    try:
                        retry = requests.get(
                            url,
                            cookies=self._merge_cookies(cookies),
                            allow_redirects=allow_redirects,
                            **self._request_kwargs()
                        )
                        if retry.status_code not in (301, 302, 303, 307, 308) and \
                                not self._is_cloudflare_challenge(retry.text, retry.status_code):
                            return retry.text, retry.status_code
                    except Exception:
                        pass
                return html, 200

        if response is not None:
            return response.text, response.status_code
        return None, None

    def _fetch_via_flaresolverr(self, url, cookies=None):
        if not FLARESOLVERR_URL:
            return None
        try:
            payload = {
                'cmd': 'request.get',
                'url': url,
                'maxTimeout': 60000,
            }
            if cookies:
                payload['cookies'] = [{'name': k, 'value': v} for k, v in cookies.items()]
            result = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
            result.raise_for_status()
            body = result.json()
            if body.get('status') != 'ok':
                return None
            solution = body.get('solution') or {}
            jar = {c['name']: c['value'] for c in (solution.get('cookies') or [])}
            clearance = jar.get('cf_clearance')
            user_agent = solution.get('userAgent')
            if clearance or user_agent:
                self._store_cf_cache(clearance, user_agent)
            return solution.get('response')
        except Exception:
            return None

    def _extract_topic_title(self, html):
        if not html or self._is_cloudflare_challenge(html):
            return None
        soup = get_soup(html)
        if soup.title and u'вход' in soup.title.text.strip().lower():
            return None
        if soup.h1 is None:
            return None
        title = soup.h1.text.strip()
        if not title or title.lower() in ('just a moment...', 'just a moment'):
            return None
        return title

    def parse_url(self, url):
        match = self.url_regex.match(url or '')
        if match is None:
            return None

        torrent_id = match.group(1)
        fallback = {'original_name': 'kinozal #{0}'.format(torrent_id)}
        try:
            normalized = self._normalize_url(url)
            html, _status = self._fetch_html(normalized, allow_redirects=True, use_flaresolverr=True)
            title = self._extract_topic_title(html)
            if title:
                return {'original_name': title}
        except Exception:
            pass
        return fallback

    def login(self, username, password):
        # Ensure we have a fresh CF session for login form.
        self._fetch_via_flaresolverr('https://{0}/'.format(KINOZAL_HOST), cookies=None)

        s = Session()
        kwargs = self._request_kwargs()
        headers = kwargs.pop('headers', None) or {}
        s.headers.update(headers)
        if self.cf_clearance:
            s.cookies.set('cf_clearance', self.cf_clearance, domain=KINOZAL_HOST)

        data = {"username": username, "password": password, 'returnto': ''}
        try:
            login_result = s.post(self.login_url, data, **kwargs)
        except Exception:
            raise KinozalLoginFailedException(2, "Failed to retrieve cookie")

        if login_result.url.startswith(self.login_url):
            raise KinozalLoginFailedException(1, "Invalid login or password")

        c_pass = s.cookies.get('pass')
        c_uid = s.cookies.get('uid')
        if not c_pass or not c_uid:
            raise KinozalLoginFailedException(2, "Failed to retrieve cookie")

        self.c_pass = c_pass
        self.c_uid = c_uid

    def verify(self):
        if not self.c_uid:
            return False
        cookies = self.get_cookies()
        if not cookies:
            return False
        html, status = self._fetch_html(self.profile_page, cookies=cookies)
        if html is None:
            return False
        if self._is_cloudflare_challenge(html, status):
            return False
        soup = get_soup(html)
        if soup.title and u'вход' in soup.title.text.strip().lower():
            return False
        return True

    def get_cookies(self):
        if not self.c_pass or not self.c_uid:
            return False
        return {'pass': self.c_pass, 'uid': self.c_uid}

    def get_id(self, url):
        match = self.url_regex.match(url or '')
        if match is None:
            return None
        return match.group(1)

    def get_last_torrent_update(self, url):
        url = self._normalize_url(url)
        html, status = self._fetch_html(url)
        if html is None or self._is_cloudflare_challenge(html, status):
            return None

        soup = get_soup(html)
        content = soup.find("div", {"class": "mn1_menu"})
        if content is None:
            return None
        text_element = content.find(lambda tag: (tag.name == 'li') and (u'Обновлен' in tag.contents))
        date_text = None
        if text_element is not None:
            text_element = text_element.find("span")
            if text_element is not None:
                date_text = text_element.string
        if date_text is None:
            text_element = content.find(lambda tag: (tag.name == 'li') and (u'Залит' in tag.contents))
            if text_element is not None:
                text_element = text_element.find("span")
                if text_element is not None:
                    date_text = text_element.string
        if date_text is None:
            return None

        parsed_datetime = self.date_parser.parse(date_text)
        return parsed_datetime.astimezone(pytz.utc)

    def get_download_url(self, url):
        torrent_id = self.get_id(url)
        if torrent_id is None:
            return None
        # dl.kinozal.guru currently returns Cloudflare 520; main domain works.
        return "https://{0}/download.php?id={1}".format(KINOZAL_HOST, torrent_id)

    def ensure_cf_session(self, probe_url=None, force=False):
        """
        Make sure cf_clearance(+UA) works for authenticated downloads.
        Prefer warming against the topic page itself — homepage cookies are not always enough.
        """
        probe = probe_url or "https://{0}/details.php?id=1".format(KINOZAL_HOST)
        if not force and self.cf_clearance and self.cf_user_agent:
            try:
                response = requests.get(
                    probe,
                    cookies=self._merge_cookies(),
                    allow_redirects=True,
                    **self._request_kwargs()
                )
                if not self._is_cloudflare_challenge(response.text, response.status_code):
                    return True
            except Exception:
                pass
        html = self._fetch_via_flaresolverr(probe, cookies=self._merge_cookies())
        return bool(html and self.cf_clearance)


class KinozalPlugin(WithCredentialsMixin, ExecuteWithHashChangeMixin, TrackerPluginBase):
    topic_class = KinozalTopic
    credentials_class = KinozalCredentials
    topic_form = [{
        'type': 'row',
        'content': [{
            'type': 'text',
            'model': 'display_name',
            'label': 'Name',
            'flex': 100
        }]
    }]

    def __init__(self):
        self.tracker = KinozalTracker(cf_cache_updater=self._persist_cf_cache)

    def _persist_cf_cache(self, clearance, user_agent):
        with DBSession() as db:
            cred = db.query(self.credentials_class).first()
            if not cred:
                return
            cred.cf_clearance = clearance
            cred.cf_user_agent = user_agent

    def login(self):
        with DBSession() as db:
            cred = db.query(self.credentials_class).first()
            if not cred:
                return LoginResult.CredentialsNotSpecified
            username = cred.username
            password = cred.password
            if not username or not password:
                return LoginResult.CredentialsNotSpecified
            self.tracker.setup(cred.c_uid, cred.c_pass, cred.cf_clearance, cred.cf_user_agent)
        try:
            self.tracker.login(username, password)
            with DBSession() as db:
                cred = db.query(self.credentials_class).first()
                cred.c_uid = self.tracker.c_uid
                cred.c_pass = self.tracker.c_pass
                cred.cf_clearance = self.tracker.cf_clearance
                cred.cf_user_agent = self.tracker.cf_user_agent
            return LoginResult.Ok
        except KinozalLoginFailedException as e:
            if e.code == 1:
                return LoginResult.IncorrentLoginPassword
            return LoginResult.Unknown
        except Exception:
            return LoginResult.Unknown

    def verify(self):
        with DBSession() as db:
            cred = db.query(self.credentials_class).first()
            if not cred:
                return False
            username = cred.username
            password = cred.password
            if not username or not password or not cred.c_uid or not cred.c_pass:
                return False
            self.tracker.setup(cred.c_uid, cred.c_pass, cred.cf_clearance, cred.cf_user_agent)
        return self.tracker.verify()

    def can_parse_url(self, url):
        return self.tracker.can_parse_url(url)

    def _load_tracker_cookies(self):
        try:
            with DBSession() as db:
                cred = db.query(self.credentials_class).first()
                if not cred or not cred.c_uid or not cred.c_pass:
                    return
                self.tracker.setup(cred.c_uid, cred.c_pass, cred.cf_clearance, cred.cf_user_agent)
        except Exception:
            return

    def parse_url(self, url):
        self._load_tracker_cookies()
        return self.tracker.parse_url(url)

    def prepare_add_topic(self, url):
        self._load_tracker_cookies()
        try:
            return super(KinozalPlugin, self).prepare_add_topic(url)
        except Exception:
            match = self.tracker.url_regex.match(url or '')
            if not match:
                return None
            return {'display_name': 'kinozal #{0}'.format(match.group(1))}

    def check_changes(self, topic):
        self._load_tracker_cookies()
        last_torrent_update = self.tracker.get_last_torrent_update(topic.url)
        topic_last_torrent_update = topic.last_torrent_update
        min_date = pytz.utc.localize(datetime.datetime.min)

        if (not last_torrent_update and not topic_last_torrent_update) or \
                (topic_last_torrent_update or min_date) < (last_torrent_update or min_date):
            topic.last_torrent_update = last_torrent_update
            return True

        return False

    def _prepare_request(self, topic):
        self._load_tracker_cookies()
        details_url = self.tracker._normalize_url(topic.url)
        # Warm/refresh CF against the same topic page before hitting download.php
        self.tracker.ensure_cf_session(probe_url=details_url)
        headers = {'Referer': details_url}
        if self.tracker.cf_user_agent:
            headers['User-Agent'] = self.tracker.cf_user_agent
        cookies = self.tracker._merge_cookies()
        url = self.tracker.get_download_url(topic.url)
        # Return URL+kwargs so download() uses requests.get with cookies explicitly.
        return url, {
            'headers': headers,
            'cookies': cookies,
            'allow_redirects': True,
            'timeout': 60,
        }


register_plugin('tracker', PLUGIN_NAME, KinozalPlugin(), upgrade)
