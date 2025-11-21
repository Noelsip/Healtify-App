import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Report from './pages/Report';
import './i18n/config';

function App() {
  return (
    <div className='min-h-screen bg-gradient-to-b from-blue-50 to-blue-200 font-poppins text-slate-800'>
      <Router>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="report" element={<Report />} />
          </Route>
        </Routes>
      </Router>
    </div>
  );
}

export default App;