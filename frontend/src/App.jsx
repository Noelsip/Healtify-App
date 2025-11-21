import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Report from './pages/Report';
import AdminLogin from './pages/admin/AdminLogin';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminClaims from './pages/admin/AdminClaims';
import AdminClaimDetail from './pages/admin/AdminClaimDetail'
import AdminDisputes from './pages/admin/AdminDisputes';
import AdminSources from './pages/admin/AdminSources';
import './i18n/config';

function App() {
  return (
    <div className='min-h-screen bg-gradient-to-b from-blue-50 to-blue-200 font-poppins text-slate-800'>
      <Router>
        <Routes>
          {/* Public Routes */}
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="report" element={<Report />} />
          </Route>

          {/* Admin Routes */}
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<AdminDashboard />} />
          <Route path="/admin/claims" element={<AdminClaims />} />
          <Route path='/admin/claims/:claimId' element={<AdminClaimDetail />}/>
          <Route path="/admin/disputes" element={<AdminDisputes />} />
          <Route path="/admin/sources" element={<AdminSources />} />
        </Routes>
      </Router>
    </div>
  );
}

export default App;