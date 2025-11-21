import { Activity } from "react";
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

const BASE_URL = 'http://localhost:8000/api';

const AdminDashboard = () => {
    const navigate = useNavigate();
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [stats, setStats] = useState({
        total_claims: 0,
        pending_claims: 0,
        approved_claims: 0,
        rejected_claims: 0
    });
    const [recentActivity, setRecentActivity] = useState([]);

    useEffect(() => {
        const token = localStorage.getItem('adminToken');
        const userData = localStorage.getItem('adminUser');

        if (!token || !userData) {
            navigate('/admin/login');
            return;
        }

        setUser(JSON.parse(userData));
        fetchDashboardData(token);
    }, [navigate]);

    const fetchDashboardData = async (token) => {
        try {
            const response = await fetch(`${BASE_URL}/admin/dashboard/stats/`, {
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
                throw new Error('Failed to fetch dashboard data');
            }

            const data = await response.json();
            setStats(data.stats);
            setRecentActivity(data.recent_activity);
            setLoading(false);
        } catch (err) {
            console.error('Error fetching dashboard data:', err);
            setError(err.message);
            setLoading(false);
        }
    };

    const handleLogout = async () => {
        const token = localStorage.getItem('adminToken');

        try {
            await fetch(`${BASE_URL}/admin/logout/`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });
        } catch (error) {
            console.error('Error during logout:', error);
        } finally {
            localStorage.removeItem('adminToken');
            localStorage.removeItem('adminRefreshToken');
            localStorage.removeItem('adminUser');
            navigate('/admin/login');
        }
    };

    const formatTimeAgo = (isoString) => {
        const date = new Date(isoString);
        const now = new Date();
        const secondsAgo = Math.floor((now - date) / 1000);

        if (secondsAgo < 60) return `${secondsAgo} seconds ago`;
        if (secondsAgo < 3600) return `${Math.floor(secondsAgo / 60)} minutes ago`;
        if (secondsAgo < 86400) return `${Math.floor(secondsAgo / 3600)} hours ago`;
        return `${Math.floor(secondsAgo / 86400)} days ago`;
    };

    if (loading) {
        return (
            <div className="flex item-center justify-center min-h-screen">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
                    <p className="text-gray-600">Loading dashboard...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-center min-h-screen">
                <div className="bg-red-50 border border-red-200 text-red-700 px-6 py-4 rounded-lg">
                    {error}
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
                            <h1 className="text-2xl font-bold text-green-900">
                                Admin Dashboard
                            </h1>
                            <p className="text-sm text-gray-600">
                                Welcome back, {user?.username}! 
                            </p>
                        </div>
                        <button
                            onClick={handleLogout}
                            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition"
                        >
                            Logout
                        </button>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                {/* Stats Card */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <StatCard 
                        title="Total Claims"
                        value={stats.total_claims}
                        icon="📊"
                        color="blue"
                    />
                    <StatCard 
                        title="Pending Dispute"
                        value={stats.pending_disputes}
                        icon="⏳"
                        color="yellow"
                    />
                    <StatCard
                        title="Total Sources"
                        value={stats.total_sources}
                        icon="📚"
                        color="green"
                    />
                    <StatCard
                        title="Verified Claims"
                        value={stats.verified_claims}
                        icon="✅"
                        color="purple"
                    />
                </div>

                {/* Quick Action */}
                <div className="bg-white rounded-lg shadow p-6 mb-8">
                    <h2 className="text-xl font-semibold mb-4">Quick Action</h2>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <ActionButton 
                            label="Manage Claims"
                            description="View and manage all claims"
                            icon="📝"
                            onClick={() => navigate('/admin/claims')}
                        />
                        <ActionButton
                            label="Review Disputes"
                            description="Handle user disputes"
                            icon="⚖️"
                            onClick={() => navigate('/admin/disputes')}
                        />
                        <ActionButton
                            label="Source Management"
                            description="Add or remove sources"
                            icon="🔍"
                            onClick={() => navigate('/admin/sources')}
                        />
                    </div>
                </div>

                {/* Recent Activity */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-xl font-semibold mb-4">Recent Activity</h2>
                    {recentActivity.length === 0 ? (
                        <p className="text-gray-500 text-center py-8">No recent activity.</p>
                    ) : (
                        <div>
                            {recentActivity.map((activity, index) => (
                                <ActivityItem
                                    key={index}
                                    text={activity.text}
                                    time={formatTimeAgo(activity.timestamp)}
                                    type={activity.type}
                                />
                            ))}
                        </div>
                    )}
                    </div>
            </main>
        </div>
    );
};

// Stat Card Component
const StatCard = ({ title, value, icon, color }) => {
    const colorClasses = {
        blue: 'bg-blue-500',
        yellow: 'bg-yellow-500',
        green: 'bg-green-500',
        purple: 'bg-purple-500'
    };

    return (
        <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-sm text-gray-600 mb-1">{title}</p>
                    <p className="text-3xl font-bold text-gray-900">{value}</p>
                </div>
                <div className={`${colorClasses[color]} w-12 h-12 rounded-full flex items-center justify-center text-2xl`}>
                    {icon}
                </div>
            </div>
        </div>
    );
};

// Action Button Component
const ActionButton = ({ title, description, icon, onClick }) => {
    return (
        <button
            onClick={onClick}
            className="bg-gray-50 hover:bg-gray-100 rounded-lg p-4 text-left transition border border-gray-200"
        >
            <div className="text-3xl mb-2">{icon}</div>
            <h3 className="font-semibold text-gray-900 mb-1">{title}</h3>
            <p className="text-sm text-gray-600">{description}</p>
        </button>
    );
};

// Activity Item Component
const ActivityItem = ({ text, time, type }) => {
    const iconMap = {
        claim: '📋',
        dispute: '⚠️',
        source: '📚'
    };

    return (
        <div className="flex items-start space-x-3 pb-4 border-b border-gray-100 last:border-0">
            <div className="text-xl">{iconMap[type] || '📌'}</div>
            <div className="flex-1">
                <p className="text-gray-900">{text}</p>
                <p className="text-sm text-gray-500">{time}</p>
            </div>
        </div>
    );
};

export default AdminDashboard;