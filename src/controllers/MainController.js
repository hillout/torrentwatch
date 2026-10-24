app.controller('MainCtrl', function ($scope, $rootScope, $http, $window, $mdSidenav, mtRoutes, GeneralService, ThemeService, $timeout) {
    $scope.routes = mtRoutes.routes.main;

    ThemeService.init();
    $scope.twThemeLabel = $rootScope.twThemeLabel;
    $scope.twThemeIcon = $rootScope.twThemeIcon;
    $scope.cycleTheme = function () {
        ThemeService.cycle();
        $scope.twThemeLabel = $rootScope.twThemeLabel;
        $scope.twThemeIcon = $rootScope.twThemeIcon;
    };

    $scope.exit = function () {
        $http.post('/api/logout').then(function () {
            $window.location.href = '/login';
        });
    };

    $http.get('/api/settings/authentication').success(function (data) {
        $scope.exit_visible = data.is_authentication_enabled;
    });

    $rootScope.$on('authentication.changed', function (e, value) {
        $scope.exit_visible = value;
    });

    $scope.newVersionUrl = null;

    function updateNewVersionUrl() {
        GeneralService.getNewVersionUrl().then(function (data){
            if (data.data.url !== null) {
                $scope.newVersionUrl = data.data.url;
            }
            $timeout(updateNewVersionUrl, 1000 * 60 * 5);
        });
    }

    updateNewVersionUrl();
});
