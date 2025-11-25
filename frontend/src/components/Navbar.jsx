import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';


const Navbar = () => {
  const { t, i18n } = useTranslation();
  const [currentLang, setCurrentLang] = useState(i18n.language);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const location = useLocation();

  const toggleLanguage = () => {
    const newLang = currentLang === 'id' ? 'en' : 'id';
    i18n.changeLanguage(newLang);
    setCurrentLang(newLang);
  };

  // Python-mudah1
  const toggleMenu = () => {
    setIsMenuOpen(!isMenuOpen);
  };

  const isActive = (path) => location.pathname === path;

  return (
    <nav className="fixed top-0 left-0 right-0 bg-blue-50 w-full p-4 shadow-sm border-b border-gray-200 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex justify-between items-center font-poppins">
        {/* Logo dan Nama */}
        <Link 
          to="/"
          className="flex items-center space-x-3 hover:opacity-80 transition-opacity"
        >
          <img src='/logo.png' alt="Healthify Logo" className="h-10 w-10" />
          <h1 className="text-2xl sm:text-3xl lg:text-4xl text-gray-800 font-poppins font-bold">Healthify</h1>
        </Link>

        {/* Grup Navigasi Tengah - hanya desktop */}
        <div className="hidden lg:flex items-center space-x-8">
          <Link
            to="/"
            className={`font-poppins font-medium transition-colors ${
              isActive('/') 
              ? 'text-blue-600 font-bold'
              : 'text-gray-700 hover:text-blue-500'
            }`}
          >
            {t('nav.home')}
          </Link>
          <Link
            to="/documentation"
            className={`font-poppins font-medium transition-colors ${
              isActive('/documentation') 
              ? 'text-blue-600 font-bold'
              : 'text-gray-700 hover:text-blue-500'
            }`}
          >
            {t('nav.documentation')}
          </Link>
          <Link 
            to="/report"
            className={`bg-blue-400 text-white px-4 py-2 rounded-3xl hover:bg-blue-600 transition-colors font-poppins font-medium ${
              isActive('/report') ? 'bg-blue-600' : ''
            }`}
          >
            {t('nav.report')}
          </Link>
          {/* Bahasa */}
          <button 
            onClick={toggleLanguage}
            className="font-poppins font-medium text-gray-700 hover:text-blue-600 transition-colors"
          >
            {t('language.toggle')}
          </button>
        </div>

        {/* Hamburger Button - Mobile & Tablet ONLY */}
        <button
          onClick={toggleMenu}
          className='lg:hidden flex flex-col space-y-1.5 p-2 hover:bg-blue-100 rounded-md transition-colors'
          aria-label="Toggle Menu"
        >
          <span className={`block w-6 h-0.5 bg-gray-700 transition-transform ${isMenuOpen ? 'rotate-45 translate-y-2' : ''}`}></span>
          <span className={`block w-6 h-0.5 bg-gray-700 transition-opacity ${isMenuOpen ? 'opacity-0' : ''}`}></span>
          <span className={`block w-6 h-0.5 bg-gray-700 transition-transform ${isMenuOpen ? '-rotate-45 -translate-y-2' : ''}`}></span>
        </button>
      </div>

      {/* Mobile & Tablet Menu */}
      <div className={`lg:hidden overflow-hidden transition-all duration-300 ${isMenuOpen ? 'max-h-64 opacity-100' : 'max-h-0 opacity-0'}`}>
        <div className="px-4 pt-4 pb-3 space-y-3 bg-blue-50">
          <Link
            to="/"
            className={`block font-poppins font-medium py-2 transition-colors ${
              isActive('/')
              ? 'text-blue-600 font-bold'
              : 'text-gray-700 hover:text-blue-500'
            }`}
            onClick={() => setIsMenuOpen(false)}
          >
            {t('nav.home')}
          </Link>
          <Link
            to="/documentation"
            className={`block font-poppins font-medium py-2 transition-colors ${
              isActive('/documentation')
              ? 'text-blue-600 font-bold'
              : 'text-gray-700 hover:text-blue-500'
            }`}
            onClick={() => setIsMenuOpen(false)}
          >
            {t('nav.documentation')}
          </Link>
          <Link 
            to="/report"
            onClick={() => setIsMenuOpen(false)}
          >
            <button className={`w-full bg-blue-400 text-white px-4 py-2 rounded-3xl hover:bg-blue-600 transition-colors font-poppins font-medium ${
              isActive('/report') ? 'bg-blue-600' : ''
            }`}>
              {t('nav.report')}
            </button>
          </Link>
          <button 
            onClick={() => {
              toggleLanguage();
              setIsMenuOpen(false);
            }}
            className="w-full text-left font-poppins font-medium text-gray-700 hover:text-blue-600 transition-colors py-2"
          >
            {t('language.toggle')}
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;