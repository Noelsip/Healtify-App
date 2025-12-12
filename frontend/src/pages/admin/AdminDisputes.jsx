import { AlertCircle, ArrowLeft, Bot, Calendar, CheckCircle2, Clock, FileText, Filter as FilterIcon, Info, Loader2, LogOut, Scale, Search, User, X, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://api.healthify.cloud/api';

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

    const handleDisputeAction = async (action, adminNotes, newLabel = null, newConfidence = 0.85) => {
        const token = localStorage.getItem('adminToken');
        setActionLoading(true);

        try {
            const labelMap = {
                'auto': null,
                'TRUE': 'valid',
                'FALSE': 'hoax',
                'MIXTURE': 'uncertain'
            };

            const mappedLabel = labelMap[newLabel];

            const payload = {
                action: action,
                review_note: adminNotes
            };
            
            // Jika bukan auto, tambahkan manual update fields
            if (newLabel && newLabel !== 'auto') {
                payload.manual_update = true;
                payload.re_verify = false;
                payload.new_label = mappedLabel;
                payload.new_confidence = newConfidence;
            } else if (action === 'approve') {
                // Jika auto, gunakan re-verify
                payload.re_verify = true;
                payload.manual_update = false;
            }

            console.log('📤 Payload yang dikirim ke backend:', payload);

            const response = await fetch(`${BASE_URL}/admin/disputes/${selectedDispute.id}/`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to process dispute action');
            }

            const data = await response.json();
            
            // Show detailed message
            let message = data.message || `Dispute ${action}ed successfully`;
            
            if (data.verification_update) {
                message += `\n\Verification Updated:\n` +
                    `Label: ${data.verification_update.label}\n` +
                    `Confidence: ${(data.verification_update.confidence * 100).toFixed(1)}%`;
            }
            
            if (data.updated_via) {
                message += `\n\nUpdated Via: ${data.updated_via.replace(/_/g, ' ')}`;
            }
            
            alert(message);
            
            setShowModal(false);
            setSelectedDispute(null);
            fetchDisputes(token);
        } catch (err) {
            console.error('Error processing dispute action:', err);
            alert(`Failed to process action: ${err.message}`);
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
            <header className="bg-gradient-to-r from-blue-600 to-cyan-600 shadow-lg">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                    <div className="flex justify-between items-center">
                        <div>
                            <div className="flex items-center gap-3 mb-2">
                                <Scale className="w-8 h-8 text-white" />
                                <h1 className="text-2xl sm:text-3xl font-bold text-white">Disputes Management</h1>
                            </div>
                            <p className="text-sm text-blue-100">Review and resolve user disputes</p>
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={() => navigate('/admin/dashboard')}
                                className="inline-flex items-center gap-2 px-4 py-2 bg-white/20 hover:bg-white/30 text-white rounded-lg transition backdrop-blur-sm border border-white/20"
                            >
                                <ArrowLeft className="w-4 h-4" />
                                Dashboard
                            </button>
                            <button
                                onClick={handleLogout}
                                className="inline-flex items-center gap-2 px-4 py-2 bg-white/20 hover:bg-white/30 text-white rounded-lg transition backdrop-blur-sm border border-white/20"
                            >
                                <LogOut className="w-4 h-4" />
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-start gap-2">
                        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                        <span>{error}</span>
                    </div>
                )}

                {/* Filter */}
                <div className="bg-white rounded-2xl shadow-xl border border-slate-100 p-6 mb-6">
                    <div className="flex items-center gap-2 mb-4">
                        <FilterIcon className="w-5 h-5 text-blue-600" />
                        <label className="block text-sm font-semibold text-gray-700">
                            Filter by Status
                        </label>
                    </div>
                    <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
                        <select
                            value={filterStatus}
                            onChange={(e) => setFilterStatus(e.target.value)}
                            className="w-full sm:w-64 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        >
                            <option value="all">All Status</option>
                            <option value="pending">Pending</option>
                            <option value="approved">Approved</option>
                            <option value="rejected">Rejected</option>
                        </select>
                        <div className="flex items-center gap-2 text-sm text-gray-600">
                            <Search className="w-4 h-4" />
                            <span>Showing <span className="font-semibold text-blue-600">{disputes.length}</span> disputes</span>
                        </div>
                    </div>
                </div>

                {/* Disputes Cards */}
                <div className="space-y-4">
                    {disputes.length === 0 ? (
                        <div className="bg-white rounded-2xl shadow-xl border border-slate-100 p-12 text-center">
                            <Scale className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                            <p className="text-gray-500 text-lg font-medium">No disputes found</p>
                            <p className="text-gray-400 text-sm mt-2">Disputes will appear here when users report issues</p>
                        </div>
                    ) : (
                        disputes.map((dispute) => {
                            const statusConfig = {
                                pending: { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-800', icon: <Clock className="w-5 h-5" /> },
                                approved: { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-800', icon: <CheckCircle2 className="w-5 h-5" /> },
                                rejected: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-800', icon: <XCircle className="w-5 h-5" /> }
                            };
                            const config = statusConfig[dispute.status] || statusConfig.pending;
                            
                            return (
                                <div 
                                    key={dispute.id} 
                                    className="bg-white rounded-2xl shadow-lg border border-slate-100 p-6 hover:shadow-xl transition-shadow"
                                >
                                    <div className="flex flex-col lg:flex-row gap-6">
                                        {/* Left Side - Content */}
                                        <div className="flex-1 space-y-4">
                                            {/* Header */}
                                            <div className="flex items-start justify-between gap-4">
                                                <div className="flex items-center gap-3">
                                                    <div className={`${config.bg} ${config.border} border p-2 rounded-lg`}>
                                                        <div className={config.text}>
                                                            {config.icon}
                                                        </div>
                                                    </div>
                                                    <div>
                                                        <div className="flex items-center gap-2">
                                                            <span className="text-xs font-bold text-gray-500">Dispute</span>
                                                            <span className="text-sm font-bold text-gray-900">#{dispute.id}</span>
                                                        </div>
                                                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-semibold rounded-full ${config.bg} ${config.text} ${config.border} border mt-1`}>
                                                            {dispute.status.toUpperCase()}
                                                        </span>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-2 text-xs text-gray-500">
                                                    <Calendar className="w-4 h-4" />
                                                    {new Date(dispute.created_at).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })}
                                                </div>
                                            </div>

                                            {/* Claim Text */}
                                            <div>
                                                <div className="flex items-center gap-2 mb-2">
                                                    <FileText className="w-4 h-4 text-blue-600" />
                                                    <label className="text-xs font-semibold text-gray-700">Claim Text</label>
                                                </div>
                                                <p className="text-sm text-gray-900 bg-gray-50 p-3 rounded-lg border border-gray-200 line-clamp-2">
                                                    {dispute.claim_text}
                                                </p>
                                            </div>

                                            {/* Reason */}
                                            <div>
                                                <div className="flex items-center gap-2 mb-2">
                                                    <AlertCircle className="w-4 h-4 text-orange-600" />
                                                    <label className="text-xs font-semibold text-gray-700">Dispute Reason</label>
                                                </div>
                                                <p className="text-sm text-gray-900 bg-orange-50 p-3 rounded-lg border border-orange-200 line-clamp-2">
                                                    {dispute.reason}
                                                </p>
                                            </div>
                                        </div>

                                        {/* Right Side - Actions */}
                                        <div className="lg:w-48 flex flex-col justify-center gap-3">
                                            <button
                                                onClick={() => handleViewDetail(dispute.id)}
                                                className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-semibold rounded-lg transition shadow-lg hover:shadow-xl"
                                            >
                                                <Search className="w-4 h-4" />
                                                Review Detail
                                            </button>
                                            {dispute.reporter_name && (
                                                <div className="flex items-center gap-2 text-xs text-gray-600 justify-center">
                                                    <User className="w-3 h-3" />
                                                    <span>{dispute.reporter_name}</span>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            );
                        })
                    )}
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
    const [newLabel, setNewLabel] = useState('auto');
    const [newConfidence, setNewConfidence] = useState(0.85);

    // ✅ MAPPING LABEL DARI FRONTEND KE BACKEND
    const labelMap = {
        'auto': null,
        'TRUE': 'valid',
        'FALSE': 'hoax',
        'MIXTURE': 'uncertain'
    };

    const handleApprove = () => {
        if (!adminNotes.trim()) {
            alert('Admin notes are required');
            return;
        }
        
        const mappedLabel = labelMap[newLabel];
        console.log(`📋 Approve action triggered:`);
        console.log(`   Label selection: ${newLabel} → ${mappedLabel}`);
        console.log(`   Confidence: ${newConfidence}`);
        console.log(`   Notes: ${adminNotes}`);
        
        onAction('approve', adminNotes, newLabel, newConfidence);
    };

    const handleReject = () => {
        if (!adminNotes.trim()) {
            alert('Admin notes are required');
            return;
        }
        
        console.log(`📋 Reject action triggered with notes: ${adminNotes}`);
        onAction('reject', adminNotes);
    };

    return (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto border border-slate-200">
                <div className="p-6 sm:p-8">
                    <div className="flex justify-between items-center mb-6">
                        <div className="flex items-center gap-3">
                            <div className="bg-gradient-to-br from-blue-500 to-cyan-600 p-2 rounded-lg">
                                <Scale className="w-6 h-6 text-white" />
                            </div>
                            <div>
                                <h2 className="text-2xl font-bold text-gray-900">
                                    Dispute #{dispute.id}
                                </h2>
                                <p className="text-sm text-gray-500">Review and resolve this dispute</p>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition"
                        >
                            <X className="w-6 h-6" />
                        </button>
                    </div>

                    <div className="space-y-5">
                        <div className="bg-gradient-to-br from-blue-50 to-white border border-blue-100 rounded-xl p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <FileText className="w-4 h-4 text-blue-600" />
                                <label className="block text-sm font-semibold text-gray-700">
                                    Claim Text
                                </label>
                            </div>
                            <p className="text-gray-900 text-sm leading-relaxed">{dispute.claim_text}</p>
                        </div>

                        <div className="bg-gradient-to-br from-orange-50 to-white border border-orange-100 rounded-xl p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <AlertCircle className="w-4 h-4 text-orange-600" />
                                <label className="block text-sm font-semibold text-gray-700">
                                    Dispute Reason
                                </label>
                            </div>
                            <p className="text-gray-900 text-sm leading-relaxed">
                                {dispute.reason}
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                                <label className="block text-xs font-semibold text-gray-600 mb-2">
                                    Current Label
                                </label>
                                <p className="text-gray-900 font-bold text-lg">{dispute.original_label || 'N/A'}</p>
                            </div>
                            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                                <label className="block text-xs font-semibold text-gray-600 mb-2">
                                    Current Confidence
                                </label>
                                <p className="text-gray-900 font-bold text-lg">
                                    {dispute.original_confidence ? `${(dispute.original_confidence * 100).toFixed(1)}%` : 'N/A'}
                                </p>
                            </div>
                        </div>

                        {dispute.status === 'pending' && (
                            <>
                                {/* New Label Override Option */}
                                <div className="bg-white border-2 border-blue-100 rounded-xl p-4">
                                    <div className="flex items-center gap-2 mb-3">
                                        <Bot className="w-5 h-5 text-blue-600" />
                                        <label className="block text-sm font-semibold text-gray-700">
                                            Action on Approval
                                        </label>
                                    </div>
                                    <select
                                        value={newLabel}
                                        onChange={(e) => setNewLabel(e.target.value)}
                                        className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent font-medium"
                                    >
                                        <option value="auto">🤖 Re-Verify with AI (Recommended)</option>
                                        <option value="TRUE">✅ Set as VALID (Klaim Benar)</option>
                                        <option value="FALSE">❌ Set as HOAX (Klaim Salah)</option>
                                        <option value="MIXTURE">⚠️ Set as UNCERTAIN (Sebagian Benar)</option>
                                    </select>
                                    <div className="mt-3 p-3 bg-blue-50 rounded-lg">
                                        <p className="text-xs text-blue-800 flex items-start gap-2">
                                            <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                                            <span>
                                                {newLabel === 'auto' 
                                                    ? 'Sistem akan menggunakan AI untuk re-verify claim berdasarkan feedback user' 
                                                    : `Akan manual-set label menjadi: ${labelMap[newLabel]?.toUpperCase()}`}
                                            </span>
                                        </p>
                                    </div>
                                </div>

                                {/* Confidence Adjustment (untuk manual update) */}
                                {newLabel !== 'auto' && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-2">
                                            Confidence Score
                                        </label>
                                        <div className="flex items-center gap-3">
                                            <input
                                                type="range"
                                                min="0"
                                                max="100"
                                                value={newConfidence * 100}
                                                onChange={(e) => setNewConfidence(e.target.value / 100)}
                                                className="flex-1"
                                            />
                                            <span className="text-lg font-semibold text-blue-600 w-16 text-right">
                                                {(newConfidence * 100).toFixed(0)}%
                                            </span>
                                        </div>
                                    </div>
                                )}

                                <div>
                                    <div className="flex items-center gap-2 mb-2">
                                        <FileText className="w-4 h-4 text-gray-600" />
                                        <label className="block text-sm font-semibold text-gray-700">
                                            Review Notes (Required)
                                        </label>
                                    </div>
                                    <textarea
                                        value={adminNotes}
                                        onChange={(e) => setAdminNotes(e.target.value)}
                                        className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                        rows="4"
                                        placeholder="Jelaskan alasan keputusan Anda..."
                                    />
                                </div>

                                <div className="bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-200 rounded-xl p-4">
                                    <div className="flex items-start gap-2 mb-3">
                                        <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                                        <p className="text-sm font-semibold text-blue-900">
                                            Yang akan terjadi saat di-approve:
                                        </p>
                                    </div>
                                    <ul className="text-sm text-blue-800 space-y-2 ml-7">
                                        <li className="flex items-start gap-2">
                                            <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
                                            <span>Status dispute berubah menjadi "Approved"</span>
                                        </li>
                                        <li className="flex items-start gap-2">
                                            <Bot className="w-4 h-4 flex-shrink-0 mt-0.5" />
                                            <span>
                                                {newLabel === 'auto' 
                                                    ? 'AI akan re-verify claim dan update label secara otomatis' 
                                                    : `Label klaim akan diubah menjadi: ${labelMap[newLabel]?.toUpperCase()}`}
                                            </span>
                                        </li>
                                        <li className="flex items-start gap-2">
                                            <User className="w-4 h-4 flex-shrink-0 mt-0.5" />
                                            <span>Email notifikasi dikirim ke user</span>
                                        </li>
                                        <li className="flex items-start gap-2">
                                            <FileText className="w-4 h-4 flex-shrink-0 mt-0.5" />
                                            <span>Hasil original dibackup di record dispute</span>
                                        </li>
                                    </ul>
                                </div>

                                <div className="flex flex-col sm:flex-row gap-3 pt-2">
                                    <button
                                        onClick={handleApprove}
                                        disabled={loading || !adminNotes.trim()}
                                        className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition shadow-lg"
                                    >
                                        {loading ? (
                                            <>
                                                <Loader2 className="w-5 h-5 animate-spin" />
                                                Processing...
                                            </>
                                        ) : (
                                            <>
                                                <CheckCircle2 className="w-5 h-5" />
                                                Approve & Update
                                            </>
                                        )}
                                    </button>
                                    <button
                                        onClick={handleReject}
                                        disabled={loading || !adminNotes.trim()}
                                        className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-700 hover:to-rose-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition shadow-lg"
                                    >
                                        {loading ? (
                                            <>
                                                <Loader2 className="w-5 h-5 animate-spin" />
                                                Processing...
                                            </>
                                        ) : (
                                            <>
                                                <XCircle className="w-5 h-5" />
                                                Reject
                                            </>
                                        )}
                                    </button>
                                    <button
                                        onClick={onClose}
                                        disabled={loading}
                                        className="px-4 py-3 bg-gray-200 hover:bg-gray-300 text-gray-900 font-semibold rounded-lg transition"
                                    >
                                        Close
                                    </button>
                                </div>
                            </>
                        )}

                        {dispute.status !== 'pending' && (
                            <div className="bg-gray-50 p-4 rounded border">
                                <p className="text-sm font-medium text-gray-700">
                                    Status: <span className="text-gray-900 font-bold uppercase">{dispute.status}</span>
                                </p>
                                {dispute.review_note && (
                                    <p className="text-sm text-gray-600 mt-2">
                                        <strong>Notes:</strong> {dispute.review_note}
                                    </p>
                                )}
                                {dispute.reviewed_at && (
                                    <p className="text-sm text-gray-500 mt-2">
                                        Direviu: {new Date(dispute.reviewed_at).toLocaleString('id-ID')}
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