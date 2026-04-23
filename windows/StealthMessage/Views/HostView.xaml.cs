using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class HostView : UserControl
{
    public HostView() => InitializeComponent();

    private HostViewModel? Vm => DataContext as HostViewModel;

    private void PortBox_ValueChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (Vm is not null && !double.IsNaN(args.NewValue))
            Vm.Port = ((int)args.NewValue).ToString();
    }

    private void MessageBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
            Vm?.SendMessageCommand.Execute(null);
    }

    private void PeersListView_SelectionChanged(object sender, SelectionChangedEventArgs e) { }

    private void KickButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null || PeersListView.SelectedItem is not PeerViewModel peer) return;
        Vm.KickCommand.Execute(peer);
    }

    private void MoveButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null || PeersListView.SelectedItem is not PeerViewModel peer) return;
        if (MoveRoomComboBox.SelectedItem is not string targetRoom) return;
        Vm.MoveCommand.Execute((peer, targetRoom));
    }

    private void ApproveButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null) return;
        var btn = sender as Microsoft.UI.Xaml.Controls.Button;
        if (btn?.Tag is PendingPeerViewModel pending)
            Vm.ApproveCommand.Execute(pending);
    }

    private void DenyButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (Vm is null) return;
        var btn = sender as Microsoft.UI.Xaml.Controls.Button;
        if (btn?.Tag is PendingPeerViewModel pending)
            Vm.DenyCommand.Execute(pending);
    }
}
