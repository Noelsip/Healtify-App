import { Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import './i18n/config';
import Documentation from './pages/Documentation';
import Home from './pages/Home';
import Report from './pages/Report';
import AdminClaimDetail from './pages/admin/AdminClaimDetail';
import AdminClaims from './pages/admin/AdminClaims';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminDisputes from './pages/admin/AdminDisputes';
import AdminJournals from './pages/admin/AdminJournals';
import AdminLogin from './pages/admin/AdminLogin';
import AdminSources from './pages/admin/AdminSources';

function App() {
  return (
    <div className='min-h-screen bg-gradient-to-b from-blue-50 to-blue-200 font-poppins text-slate-800'>
      <Router>
        <Routes>
          {/* Public Routes */}
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="documentation" element={<Documentation />} />
            <Route path="report" element={<Report />} />
          </Route>

          {/* Admin Routes */}
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/admin/claims" element={<AdminClaims />} />
          <Route path='/admin/claims/:claimId' element={<AdminClaimDetail />}/>
          <Route path="/admin/disputes" element={<AdminDisputes />} />
          <Route path="/admin/sources" element={<AdminSources />} />
          <Route path="/admin/journals" element={<AdminJournals />} />
        </Routes>
      </Router>
    </div>
  );
}

export default App;