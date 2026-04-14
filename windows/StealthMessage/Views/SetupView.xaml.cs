using Microsoft.UI.Xaml.Controls;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class SetupView : UserControl
{
    public SetupView()
    {
        InitializeComponent();
    }

    private SetupViewModel? Vm => DataContext as SetupViewModel;

    // PasswordBox.Password is not a DependencyProperty — wire it manually
    private void PassBox_PasswordChanged(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null) return;
        var ss = new System.Security.SecureString();
        foreach (char c in PassBox.Password) ss.AppendChar(c);
        ss.MakeReadOnly();
        Vm.Passphrase = ss;
    }

    private void ConfirmPassBox_PasswordChanged(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null) return;
        var ss = new System.Security.SecureString();
        foreach (char c in ConfirmPassBox.Password) ss.AppendChar(c);
        ss.MakeReadOnly();
        Vm.ConfirmPassphrase = ss;
    }
}
