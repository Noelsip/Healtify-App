import React from 'react';
import { useTranslation } from 'react-i18next';
import githubIcon from '../assets/github.png';
import gmailIcon from '../assets/gmail.png';
import linkedinIcon from '../assets/linkedin.png';
import logoHealthify from '../assets/logo.png';

const Footer = () => {
    const { t } = useTranslation();
    
    const socialLinks = [
        {
            name: 'GitHub',
            url: 'https://github.com/Noelsip',
            iconPath: githubIcon,
            bgColor: 'bg-white',
            hoverColor: 'hover:bg-gray-700'
        },
        {
            name: 'Gmail',
            url: 'mailto:11231072@student.itk.ac.id',
            iconPath: gmailIcon,
            bgColor: 'bg-white', 
            hoverColor: 'hover:bg-gray-100'
        },
        {
            name: 'LinkedIn',
            url: 'https://www.linkedin.com/in/noelsipayung/',
            iconPath: linkedinIcon,
            bgColor: 'bg-white', 
            hoverColor: 'hover:bg-[#006399]'
        }
    ];

    const footerLinks = [
        { name: t('footer.about'), url: '/tentang' },
        { name: t('footer.documentation'), url: '/documentation' },
        { name: t('footer.report'), url: '/report' }
    ];

    return (
        <footer className="relative bg-[#004AAD] text-white py-12 font-poppins shadow-inner shadow-black/20"> 
            <div className="absolute top-0 left-0 w-full h-1 bg-white/10 opacity-50"></div>

            <div className="container mx-auto px-6 max-w-7xl">
                <div className="flex flex-col md:flex-row justify-between items-start gap-12 mb-10">
                    <div className="flex flex-col gap-4 w-full md:w-1/3">
                        <div className="flex items-center gap-3">
                            <img 
                                src={logoHealthify} 
                                alt="Healthify Logo" 
                                className="h-16 md:h-20 w-16 md:w-20 object-contain"
                            />
                            <span className="text-2xl md:text-3xl font-bold tracking-tight">{t('footer.title')}</span> 
                        </div>
                    </div>
                    
                    <div className="w-full md:w-1/3 text-center md:pt-1">
                        <h4 className="font-bold mb-4 text-lg tracking-wider">{t('footer.learnMore')}</h4>
                        
                        <div className="flex flex-wrap justify-center items-center gap-x-3 gap-y-2">
                            {footerLinks.map((link, idx) => (
                                <React.Fragment key={idx}>
                                    <a 
                                        href={link.url} 
                                        className="text-blue-100 hover:text-white hover:underline transition-colors text-sm font-medium"
                                    >
                                        {link.name}
                                    </a>
                                    {idx < footerLinks.length - 1 && (
                                        <span className="text-blue-400 text-sm">•</span>
                                    )}
                                </React.Fragment>
                            ))}
                        </div>
                    </div>

                    <div className="w-full md:w-1/3 text-left md:text-right md:pt-1">
                        <h4 className="font-bold mb-4 text-lg tracking-wider">{t('footer.contact')}</h4>
                        
                        <div className="flex gap-4 justify-start md:justify-end">
                            {socialLinks.map((social, idx) => (
                                <a 
                                    key={idx}
                                    href={social.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={`${social.bgColor} ${social.hoverColor} w-10 h-10 rounded-full flex items-center justify-center transition-all hover:scale-110 shadow-lg`} 
                                    aria-label={social.name}
                                    title={social.name}
                                >
                                    <img 
                                        src={social.iconPath} 
                                        alt={`${social.name} icon`} 
                                        className="w-5 h-5 object-contain"
                                    />
                                </a>
                            ))}
                        </div>
                    </div>
                </div>

                <div className="border-t border-blue-600 pt-6 text-center">
                    <p className="text-blue-200 text-sm">
                        {t('footer.copyright')}
                    </p>
                </div>
            </div>
        </footer>
    );
};

export default Footer;