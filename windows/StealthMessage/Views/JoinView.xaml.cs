using System.Collections.Specialized;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using StealthMessage.ViewModels;

namespace StealthMessage.Views;

public sealed partial class JoinView : UserControl
{
    // Track the ViewModel we are subscribed to so we can unsubscribe when it changes.
    // WinUI 3 DataContextChangedEventArgs only has NewValue, so we manage old-VM ourselves.
    private JoinViewModel? _subscribedVm;

    public JoinView()
    {
        InitializeComponent();

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
        // Defer to the next layout pass (Low priority) so the new item is measured before
        // we scroll.  Using ChangeView on the ScrollViewer avoids the re-virtualization
        // flicker that ListView.ScrollIntoView triggers in WinUI 3.
        _ = DispatcherQueue.TryEnqueue(
            Microsoft.UI.Dispatching.DispatcherQueuePriority.Low,
            () => MessageScroller.ChangeView(null, double.MaxValue, null, disableAnimation: true));
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
