using System.Windows.Input;

namespace StealthMessage.ViewModels;

/// <summary>
/// Minimal ICommand implementation that delegates execution to an async delegate.
/// </summary>
internal sealed class RelayCommand : ICommand
{
    private readonly Func<Task>  _execute;
    private readonly Func<bool>? _canExecute;
    private bool                 _isExecuting;

    public RelayCommand(Func<Task> execute, Func<bool>? canExecute = null)
    {
        _execute    = execute;
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter)
        => !_isExecuting && (_canExecute?.Invoke() ?? true);

    public async void Execute(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        _isExecuting = true;
        NotifyCanExecuteChanged();
        try   { await _execute(); }
        finally
        {
            _isExecuting = false;
            NotifyCanExecuteChanged();
        }
    }

    public void NotifyCanExecuteChanged()
        => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}

/// <summary>Synchronous variant for simple commands.</summary>
internal sealed class SyncRelayCommand : ICommand
{
    private readonly Action     _execute;
    private readonly Func<bool>? _canExecute;

    public SyncRelayCommand(Action execute, Func<bool>? canExecute = null)
    {
        _execute    = execute;
        _canExecute = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter) => _canExecute?.Invoke() ?? true;

    public void Execute(object? parameter)
    {
        if (CanExecute(parameter)) _execute();
    }

    public void NotifyCanExecuteChanged()
        => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
}
