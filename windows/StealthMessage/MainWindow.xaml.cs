using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using StealthMessage.ViewModels;
using StealthMessage.Views;

namespace StealthMessage;

public sealed partial class MainWindow : Window
{
    private readonly AppViewModel _appVm;

    public MainWindow(AppViewModel appVm)
    {
        InitializeComponent();
        _appVm = appVm;

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");

        _appVm.PropertyChanged += OnAppViewModelChanged;
        UpdateContent(_appVm.CurrentScreen);
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
