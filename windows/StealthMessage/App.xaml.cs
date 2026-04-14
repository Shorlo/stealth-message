using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.UI.Xaml;
using StealthMessage.Crypto;
using StealthMessage.ViewModels;

namespace StealthMessage;

/// <summary>
/// Application bootstrap: configures DI and launches MainWindow.
/// </summary>
public partial class App : Application
{
    public static IServiceProvider Services { get; private set; } = null!;
    private Window? _window;

    public App()
    {
        InitializeComponent();
        Services = ConfigureServices();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var appVm = Services.GetRequiredService<AppViewModel>();
        appVm.Initialize();

        _window = new MainWindow(appVm);
        _window.Activate();
    }

    private static IServiceProvider ConfigureServices()
    {
        var services = new ServiceCollection();

        services.AddLogging(b => b.AddDebug());

        // Crypto
        services.AddSingleton<PgpManager>();
        services.AddSingleton<KeyStore>();

        // Root ViewModel
        services.AddSingleton<AppViewModel>();

        return services.BuildServiceProvider();
    }
}
