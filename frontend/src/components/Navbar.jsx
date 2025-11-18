import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Logo from '../assets/logo.png';

const Navbar = () => {
  const { t, i18n } = useTranslation();
  const [currentLang, setCurrentLang] = useState(i18n.language);

  const toggleLanguage = () => {
    const newLang = currentLang === 'id' ? 'en' : 'id';
    i18n.changeLanguage(newLang);
    setCurrentLang(newLang);
  };

  return (
    <nav className="fixed top-0 left-0 right-0 bg-blue-50 w-full p-4 shadow-sm border-b border-gray-200 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex justify-between items-center font-poppins">
        {/* Logo dan Nama */}
        <a 
          href="/"
          className="flex items-center space-x-3 hover:opacity-80 transition-opacity"
        >
          <img src={Logo} alt="Healthify Logo" className="h-10 w-10" />
          <h1 className="text-4xl text-gray-800 font-poppins font-bold">Healthify</h1>
        </a>

        {/* Grup Navigasi Tengah */}
        <div className="flex items-center space-x-8">
          <a href="/" className="text-gray-700 hover:text-blue-500 transition-colors font-poppins font-medium">
            {t('nav.home')}
          </a>
          <a href="#dokumentasi" className="text-gray-700 hover:text-blue-500 transition-colors font-poppins font-medium">
            {t('nav.documentation')}
          </a>
          <a href="#laporkan">
            <button className="bg-blue-400 text-white px-4 py-2 rounded-3xl hover:bg-blue-600 transition-colors font-poppins font-medium">
              {t('nav.report')}
            </button>
          </a>
          {/* Bahasa */}
          <button 
            onClick={toggleLanguage}
            className="font-poppins font-medium text-gray-700 hover:text-blue-600 transition-colors"
          >
            {t('language.toggle')}
          </button>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;