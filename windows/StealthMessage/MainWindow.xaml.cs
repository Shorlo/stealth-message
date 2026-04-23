using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using StealthMessage.ViewModels;
using StealthMessage.Views;
using Windows.Graphics;

namespace StealthMessage;

public sealed partial class MainWindow : Window
{
    private readonly AppViewModel _appVm;
    private bool _initialSizeSet;

    public MainWindow(AppViewModel appVm)
    {
        InitializeComponent();
        _appVm = appVm;

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");

        this.Activated += OnFirstActivated;

        _appVm.PropertyChanged += OnAppViewModelChanged;
        UpdateContent(_appVm.CurrentScreen);
    }

    private void OnFirstActivated(object sender, WindowActivatedEventArgs e)
    {
        if (_initialSizeSet) return;
        _initialSizeSet = true;

        double scale = Content.XamlRoot?.RasterizationScale ?? 1.0;
        int w = (int)(900 * scale);
        int h = (int)(660 * scale);
        AppWindow.Resize(new SizeInt32(w, h));

        // Center on the display this window is on
        var display = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Nearest);
        var work    = display.WorkArea;
        AppWindow.Move(new PointInt32(
            work.X + (work.Width  - w) / 2,
            work.Y + (work.Height - h) / 2));
    }

    private void OnAppViewModelChanged(object? sender,
        System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(AppViewModel.CurrentScreen))
            DispatcherQueue.TryEnqueue(() => UpdateContent(_appVm.CurrentScreen));
    }

    private void UpdateContent(Screen screen)
    {
        RootContent.Content = screen switch
        {
            Screen.Setup   => new SetupView   { DataContext = _appVm.CurrentViewModel },
            Screen.Unlock  => new UnlockView  { DataContext = _appVm.CurrentViewModel },
            Screen.Hub     => new HubView     { DataContext = _appVm.CurrentViewModel },
            Screen.Host    => new HostView    { DataContext = _appVm.CurrentViewModel },
            Screen.Join    => new JoinView    { DataContext = _appVm.CurrentViewModel },
            _              => new Grid()
        };
    }
}
