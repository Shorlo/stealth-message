using System.Collections.Specialized;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class JoinView : UserControl
{
    // Track the ViewModel we are currently subscribed to so we can unsubscribe when it changes.
    private JoinViewModel? _subscribedVm;

    public JoinView()
    {
        InitializeComponent();

        // Subscribe / unsubscribe from Messages when the ViewModel changes so the
        // ListView always scrolls to the bottom when a new message arrives.
        // WinUI 3 DataContextChangedEventArgs only exposes NewValue — track old VM ourselves.
        DataContextChanged += (_, e) =>
        {
            if (_subscribedVm is not null)
                _subscribedVm.Messages.CollectionChanged -= OnMessagesChanged;
            _subscribedVm = e.NewValue as JoinViewModel;
            if (_subscribedVm is not null)
                _subscribedVm.Messages.CollectionChanged += OnMessagesChanged;
        };
    }

    private JoinViewModel? Vm => DataContext as JoinViewModel;

    private void OnMessagesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action != NotifyCollectionChangedAction.Add) return;
        int count = MessageList.Items.Count;
        if (count > 0)
            MessageList.ScrollIntoView(MessageList.Items[count - 1]);
    }

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
