import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const AdminDisputes = () => {
    const navigate = useNavigate();
    const [disputes, setDisputes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [filterStatus, setFilterStatus] = useState('all');
    const [selectedDispute, setSelectedDispute] = useState(null);
    const [showModal, setShowModal] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);

    useEffect(() => {
        const token = localStorage.getItem('adminToken');
        if (!token) {
            navigate('/admin/login');
            return;
        }
        fetchDisputes(token);
    }, [navigate, filterStatus]);

    const fetchDisputes = async (token) => {
        setLoading(true);
        try {
            const url = filterStatus === 'all' 
                ? `${BASE_URL}/admin/disputes/`
                : `${BASE_URL}/admin/disputes/?status=${filterStatus}`;

            const response = await fetch(url, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.status === 401) {
                localStorage.clear();
                navigate('/admin/login');
                return;
            }

            if (!response.ok) {
                throw new Error('Failed to fetch disputes');
            }

            const data = await response.json();
            setDisputes(data.disputes || []);
            setLoading(false);
        } catch (err) {
            console.error('Error fetching disputes:', err);
            setError('Failed to load disputes');
            setLoading(false);
        }
    };

    const handleViewDetail = async (disputeId) => {
        const token = localStorage.getItem('adminToken');
        try {
            const response = await fetch(`${BASE_URL}/admin/disputes/${disputeId}/`, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) throw new Error('Failed to fetch dispute details');

            const data = await response.json();
            setSelectedDispute(data);
            setShowModal(true);
        } catch (err) {
            console.error('Error fetching dispute details:', err);
            alert('Failed to load dispute details');
        }
    };

    const handleDisputeAction = async (action, adminNotes, newLabel = null) => {
        const token = localStorage.getItem('adminToken');
        setActionLoading(true);

        try {
            const payload = {
                action: action,
                admin_notes: adminNotes
            };
            
            // Tambahkan new_label jika ada
            if (newLabel) {
                payload.new_label = newLabel;
            }

            const response = await fetch(`${BASE_URL}/admin/disputes/${selectedDispute.id}/action/`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) throw new Error('Failed to process dispute action');

            const data = await response.json();
            
            // Show detailed message
            let message = data.message;
            if (data.verification_updated) {
                message += `\n\nVerification Updated:\n` +
                    `${data.verification_updated.old_label} (${(data.verification_updated.old_confidence * 100).toFixed(1)}%) → ` +
                    `${data.verification_updated.new_label} (${(data.verification_updated.new_confidence * 100).toFixed(1)}%)`;
            } else if (data.verification_created) {
                message += `\n\nVerification Created:\n` +
                    `Label: ${data.verification_created.label} (${(data.verification_created.confidence * 100).toFixed(1)}%)`;
            }
            
            alert(message);
            
            setShowModal(false);
            setSelectedDispute(null);
            fetchDisputes(token);
        } catch (err) {
            console.error('Error processing dispute action:', err);
            alert('Failed to process action');
        } finally {
            setActionLoading(false);
        }
    };

    const handleLogout = () => {
        localStorage.clear();
        navigate('/admin/login');
    };

    const getStatusColor = (status) => {
        const colors = {
            'pending': 'bg-yellow-100 text-yellow-800',
            'approved': 'bg-green-100 text-green-800',
            'rejected': 'bg-red-100 text-red-800'
        };
        return colors[status] || 'bg-gray-100 text-gray-800';
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p className="text-gray-600">Loading disputes...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Header */}
            <header className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
                    <div className="flex justify-between items-center">
                        <div>
                            <h1 className="text-2xl font-bold text-gray-900">Disputes Management</h1>
                            <p className="text-sm text-gray-600">Review and resolve user disputes</p>
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={() => navigate('/admin/dashboard')}
                                className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg transition"
                            >
                                ← Dashboard
                            </button>
                            <button
                                onClick={handleLogout}
                                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition"
                            >
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6">
                        {error}
                    </div>
                )}

                {/* Filter */}
                <div className="bg-white rounded-lg shadow p-6 mb-6">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Filter by Status
                    </label>
                    <select
                        value={filterStatus}
                        onChange={(e) => setFilterStatus(e.target.value)}
                        className="w-full md:w-64 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                        <option value="all">All Status</option>
                        <option value="pending">Pending</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                    </select>

                    <div className="mt-4 text-sm text-gray-600">
                        Showing {disputes.length} disputes
                    </div>
                </div>

                {/* Disputes Table */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        ID
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Claim Text
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        User Feedback
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Status
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Created
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Actions
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {disputes.length === 0 ? (
                                    <tr>
                                        <td colSpan="6" className="px-6 py-8 text-center text-gray-500">
                                            No disputes found
                                        </td>
                                    </tr>
                                ) : (
                                    disputes.map((dispute) => (
                                        <tr key={dispute.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                                #{dispute.id}
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-900 max-w-md">
                                                <div className="truncate">{dispute.claim_text}</div>
                                            </td>
                                            <td className="px-6 py-4 text-sm text-gray-900 max-w-xs">
                                                <div className="truncate">{dispute.user_feedback}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <span className={`px-2 py-1 text-xs font-semibold rounded-full ${getStatusColor(dispute.status)}`}>
                                                    {dispute.status.toUpperCase()}
                                                </span>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                {new Date(dispute.created_at).toLocaleDateString()}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                <button
                                                    onClick={() => handleViewDetail(dispute.id)}
                                                    className="text-blue-600 hover:text-blue-900 font-medium"
                                                >
                                                    Review
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </main>

            {/* Modal for Dispute Detail */}
            {showModal && selectedDispute && (
                <DisputeModal
                    dispute={selectedDispute}
                    onClose={() => {
                        setShowModal(false);
                        setSelectedDispute(null);
                    }}
                    onAction={handleDisputeAction}
                    loading={actionLoading}
                    getStatusColor={getStatusColor}
                />
            )}
        </div>
    );
};
// Dispute Modal Component with Label Selection
const DisputeModal = ({ dispute, onClose, onAction, loading }) => {
    const [adminNotes, setAdminNotes] = useState('');
    const [newLabel, setNewLabel] = useState('auto'); // 'auto', 'TRUE', 'FALSE', 'MIXTURE'

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                <div className="p-6">
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-2xl font-bold text-gray-900">
                            Dispute #{dispute.id}
                        </h2>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl"
                        >
                            ✕
                        </button>
                    </div>

                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Claim Text
                            </label>
                            <p className="text-gray-900 bg-gray-50 p-3 rounded border">{dispute.claim_text}</p>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                User Feedback
                            </label>
                            <p className="text-gray-900 bg-yellow-50 p-3 rounded border border-yellow-200">
                                {dispute.user_feedback}
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Current Label
                                </label>
                                <p className="text-gray-900 font-semibold">{dispute.original_label || 'N/A'}</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    Current Confidence
                                </label>
                                <p className="text-gray-900 font-semibold">
                                    {dispute.original_confidence ? `${(dispute.original_confidence * 100).toFixed(1)}%` : 'N/A'}
                                </p>
                            </div>
                        </div>

                        {dispute.status === 'pending' && (
                            <>
                                {/* New Label Override Option */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-2">
                                        New Label (When Approving)
                                    </label>
                                    <select
                                        value={newLabel}
                                        onChange={(e) => setNewLabel(e.target.value)}
                                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                    >
                                        <option value="auto">Auto (Analyze from feedback)</option>
                                        <option value="TRUE">TRUE</option>
                                        <option value="FALSE">FALSE</option>
                                        <option value="MIXTURE">MIXTURE</option>
                                    </select>
                                    <p className="text-xs text-gray-500 mt-1">
                                        {newLabel === 'auto' 
                                            ? 'System will analyze user feedback to determine new label' 
                                            : `Will update claim label to: ${newLabel}`}
                                    </p>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-2">
                                        Admin Notes (Optional)
                                    </label>
                                    <textarea
                                        value={adminNotes}
                                        onChange={(e) => setAdminNotes(e.target.value)}
                                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                        rows="3"
                                        placeholder="Add notes about your decision..."
                                    />
                                </div>

                                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                                    <p className="text-sm font-medium text-blue-900 mb-2">
                                        ℹ️ What happens when you approve:
                                    </p>
                                    <ul className="text-sm text-blue-800 space-y-1 ml-4 list-disc">
                                        <li>Dispute status will be marked as "Approved"</li>
                                        <li>Claim verification label will be updated to: <strong>{newLabel === 'auto' ? 'Auto-determined' : newLabel}</strong></li>
                                        <li>Confidence will be set to 95% (admin verified)</li>
                                        <li>Original values are backed up in dispute record</li>
                                    </ul>
                                </div>

                                <div className="flex gap-3">
                                    <button
                                        onClick={() => onAction('approve', adminNotes, newLabel === 'auto' ? null : newLabel)}
                                        disabled={loading}
                                        className="flex-1 px-4 py-3 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition disabled:bg-gray-400"
                                    >
                                        {loading ? 'Processing...' : '✓ Approve & Update Verification'}
                                    </button>
                                    <button
                                        onClick={() => onAction('reject', adminNotes)}
                                        disabled={loading}
                                        className="flex-1 px-4 py-3 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg transition disabled:bg-gray-400"
                                    >
                                        {loading ? 'Processing...' : '✗ Reject Dispute'}
                                    </button>
                                </div>
                            </>
                        )}

                        {dispute.status !== 'pending' && (
                            <div className="bg-gray-50 p-4 rounded border">
                                <p className="text-sm font-medium text-gray-700">
                                    Status: <span className="text-gray-900 uppercase">{dispute.status}</span>
                                </p>
                                {dispute.admin_notes && (
                                    <p className="text-sm text-gray-600 mt-2">
                                        <strong>Admin Notes:</strong> {dispute.admin_notes}
                                    </p>
                                )}
                                {dispute.resolved_at && (
                                    <p className="text-sm text-gray-500 mt-2">
                                        Resolved: {new Date(dispute.resolved_at).toLocaleString()}
                                    </p>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default AdminDisputes;