app.factory('ThemeService', ['$window', '$rootScope', function ($window, $rootScope) {
    var STORAGE_KEY = 'torrentwatch.theme';
    var MODES = ['system', 'light', 'dark'];
    var LABELS = {
        system: 'System',
        light: 'Light',
        dark: 'Dark'
    };
    var ICONS = {
        system: 'content/icons/theme-system.svg',
        light: 'content/icons/theme-light.svg',
        dark: 'content/icons/theme-dark.svg'
    };

    function readStored() {
        var value = $window.localStorage.getItem(STORAGE_KEY);
        return MODES.indexOf(value) >= 0 ? value : 'system';
    }

    function resolveEffective(mode) {
        if (mode === 'light' || mode === 'dark') {
            return mode;
        }
        if ($window.matchMedia && $window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    function apply(mode) {
        var root = $window.document.documentElement;
        root.setAttribute('data-theme', mode);
        var effective = resolveEffective(mode);
        root.setAttribute('data-theme-effective', effective);
        var meta = $window.document.querySelector('meta[name="theme-color"]');
        if (meta) {
            meta.setAttribute('content', effective === 'dark' ? '#0b1220' : '#f4f1ea');
        }
        $rootScope.twTheme = mode;
        $rootScope.twThemeLabel = LABELS[mode];
        $rootScope.twThemeIcon = ICONS[mode];
        $rootScope.twThemeEffective = effective;
    }

    function set(mode) {
        if (MODES.indexOf(mode) < 0) {
            mode = 'system';
        }
        $window.localStorage.setItem(STORAGE_KEY, mode);
        apply(mode);
    }

    function cycle() {
        var current = readStored();
        var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
        set(next);
        return next;
    }

    function init() {
        apply(readStored());
        if ($window.matchMedia) {
            var mq = $window.matchMedia('(prefers-color-scheme: dark)');
            var onChange = function () {
                if (readStored() === 'system') {
                    apply('system');
                    if (!$rootScope.$$phase) {
                        $rootScope.$applyAsync();
                    }
                }
            };
            if (mq.addEventListener) {
                mq.addEventListener('change', onChange);
            } else if (mq.addListener) {
                mq.addListener(onChange);
            }
        }
    }

    return {
        modes: MODES,
        labels: LABELS,
        icons: ICONS,
        init: init,
        get: readStored,
        set: set,
        cycle: cycle,
        resolveEffective: resolveEffective
    };
}]);
