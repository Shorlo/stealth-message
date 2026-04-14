using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class UnlockView : UserControl
{
    public UnlockView()
    {
        InitializeComponent();
    }

    private UnlockViewModel? Vm => DataContext as UnlockViewModel;

    private void PassBox_PasswordChanged(object sender, RoutedEventArgs e)
    {
        if (Vm is null) return;
        var ss = new System.Security.SecureString();
        foreach (char c in PassBox.Password) ss.AppendChar(c);
        ss.MakeReadOnly();
        Vm.Passphrase = ss;
    }

    private void PassBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
            Vm?.UnlockCommand.Execute(null);
    }

    private async void ResetIdentity_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title            = "Reset identity",
            Content          = "This will permanently delete your keypair and all local data. Are you sure?",
            PrimaryButtonText   = "Reset",
            CloseButtonText     = "Cancel",
            DefaultButton    = ContentDialogButton.Close,
            XamlRoot         = XamlRoot,
        };
        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary)
            Vm?.ResetIdentityCommand.Execute(null);
    }
}
