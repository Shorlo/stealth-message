using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class JoinView : UserControl
{
    public JoinView() => InitializeComponent();

    private JoinViewModel? Vm => DataContext as JoinViewModel;

    private void MessageBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
            Vm?.SendMessageCommand.Execute(null);
    }

    private void BackButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        Vm?.ReturnToHub();
    }
}
