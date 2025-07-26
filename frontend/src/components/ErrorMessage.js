import React from 'react';
import { FaExclamationTriangle, FaTimes } from 'react-icons/fa';

const ErrorMessage = ({ message, onClose }) => {
  return (
    <div className="fixed top-4 right-4 z-50 max-w-md slide-up">
      <div className="bg-red-500 text-white rounded-lg shadow-lg p-4">
        <div className="flex items-start space-x-3">
          <FaExclamationTriangle className="text-xl mt-0.5 flex-shrink-0" />
          
          <div className="flex-1">
            <h4 className="font-semibold mb-1">오류가 발생했습니다</h4>
            <p className="text-sm opacity-90">{message}</p>
          </div>
          
          <button
            onClick={onClose}
            className="text-white/80 hover:text-white transition-colors"
          >
            <FaTimes />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ErrorMessage;