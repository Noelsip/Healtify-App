import { useEffect } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'react-feather';

const Toast = ({ message, type = 'success', onClose, duration = 4000 }) => {
    useEffect(() => {
        const timer = setTimeout(() => {
            onClose();
        }, duration);

        return () => clearTimeout(timer);
    }, [duration, onClose]);

    const icons = {
        success: <CheckCircle className="w-5 h-5 text-green-500" />,
        error: <XCircle className="w-5 h-5 text-red-500" />,
        warning: <AlertTriangle className="w-5 h-5 text-yellow-500" />,
        info: <Info className="w-5 h-5 text-blue-500" />
    };

    const colors = {
        success: 'bg-green-50 border-green-200 text-green-800',
        error: 'bg-red-50 border-red-200 text-red-800',
        warning: 'bg-yellow-50 border-yellow-200 text-yellow-800',
        info: 'bg-blue-50 border-blue-200 text-blue-800'
    };

    const progressColors = {
        success: 'bg-green-500',
        error: 'bg-red-500',
        warning: 'bg-yellow-500',
        info: 'bg-blue-500'
    };

    return (
        <div className="fixed top-4 right-4 z-50 animate-fade-in">
            <div className={`${colors[type]} border rounded-lg shadow-lg p-4 min-w-[300px] max-w-md`}>
                <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                        {icons[type]}
                    </div>
                    <div className="flex-1">
                        <p className="text-sm font-medium break-words">{message}</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
                {/* Progress bar */}
                <div className="mt-2 h-1 bg-gray-200 rounded-full overflow-hidden">
                    <div 
                        className={`h-full ${progressColors[type]} animate-progress`}
                        style={{
                            animation: `progress ${duration}ms linear`
                        }}
                    ></div>
                </div>
            </div>
        </div>
    );
};

export default Toast;