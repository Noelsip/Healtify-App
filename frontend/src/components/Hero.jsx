import { Search, Share2, FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from 'react-i18next';
import { copyToClipboard, shareContent } from '../utils/shareUtils';

const Hero = () => {
    const { t } = useTranslation();
    const [notification, setNotification] = useState('');
    const [searchQuery, setSearchQuery] = useState('');

    const showNotification = (message) => {
        setNotification(message);
        setTimeout(() => setNotification(''), 3000);
    };

    const handleShare = async () => {
        const result = await shareContent({
            title: 'Healthify - ' + t('hero.desc'),
            text: t('hero.subtitle'),
            url: window.location.href
        });
        
        if (result.success) {
            showNotification(t('actions.shareSuccess'));
        }
    };

    const handleCopy = async () => {
        const result = await copyToClipboard(window.location.href);
        
        if (result.success) {
            showNotification(t('actions.copied'));
        }
    };

    const handleSearch = (e) => {
        e.preventDefault();
        // TODO: Implementasi search logic
        console.log('Searching:', searchQuery);
    };

    return (
        <section className="flex flex-col items-center max-w-4xl mx-auto text-center px-4">
            {/* Title */}
            <div className="mb-6 relative">
                <h1 className="text-4xl md:text-5xl text-gray-700 font-bold font-poppins">
                    {t('hero.title')}
                    <Search className="inline-block w-8 h-8 md:w-10 md:h-10 text-blue-400 ml-2 -mt-2 stroke-[3]"/>
                </h1>
            </div>
            <p className="text-slate-600 text-base md:text-lg mb-8">
                {t('hero.subtitle')}
            </p>

            {/* Search Box */}
            <form onSubmit={handleSearch} className="w-full max-w-2xl bg-white p-2 rounded-full shadow-xl flex items-center mb-12 border border-slate-200">
                <input 
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('hero.searchPlaceholder')}
                    className="flex-1 px-6 py-3 outline-none text-slate-700 placeholder:text-slate-400 bg-transparent"
                />
                <button 
                    type="submit"
                    className="bg-blue-500 hover:bg-blue-600 text-white px-6 md:px-8 py-3 rounded-full font-medium transition whitespace-nowrap"
                >
                    {t('hero.verifyButton')}
                </button>
            </form>

            {/* Result Card */}
            <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden text-left relative w-full">
                {/* Top Blue Bar */}
                <div className="h-2 bg-blue-500 w-full"></div>

                <div className="p-6 md:p-8">
                    {/* Badges */}
                    <div className="flex flex-wrap gap-3 mb-6 justify-end">
                        <span className="bg-green-600 text-white px-4 py-1.5 rounded text-xs md:text-sm font-bold">
                            {t('hero.badges.valid')}
                        </span>
                        <span className="bg-amber-400 text-white px-4 py-1.5 rounded text-xs md:text-sm font-bold">
                            {t('hero.badges.confidence')}: 100%
                        </span>
                        <span className="bg-blue-600 text-white px-4 py-1.5 rounded text-xs md:text-sm font-bold">
                            {t('hero.badges.evaluation')}: 0.5
                        </span>
                    </div>

                    {/* Context Text */}
                    <p className="text-slate-600 leading-relaxed mb-6 text-sm md:text-base text-justify">
                        Lorem ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry's standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to make a type specimen book. It has survived not only five centuries, but also the leap into electronic typesetting, remaining essentially unchanged.
                    </p>

                    {/* References */}
                    <div className="mb-6">
                        <h4 className="font-bold text-slate-800 mb-2">{t('hero.reference')}</h4>
                        <ul className="text-sm text-blue-500 space-y-1.5">
                            <li>
                                <a 
                                    href="https://doi.org/10.64628/aan.pasfrwmq5" 
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="underline hover:text-blue-700 break-all"
                                >
                                    1. https://doi.org/10.64628/aan.pasfrwmq5
                                </a>
                            </li>
                            <li>
                                <a 
                                    href="https://doi.org/10.64628/aan.pasfrwmq5" 
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="underline hover:text-blue-700 break-all"
                                >
                                    2. https://doi.org/10.64628/aan.pasfrwmq5
                                </a>
                            </li>
                        </ul>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex flex-wrap gap-4 justify-end text-sm">
                        <button 
                            onClick={handleShare}
                            className="flex items-center gap-2 text-blue-500 hover:text-blue-700 transition-colors"
                        >
                            <Share2 className="w-5 h-5"/> 
                            {t('actions.share')}
                        </button>
                        <button 
                            onClick={handleCopy}
                            className="flex items-center gap-2 text-blue-500 hover:text-blue-700 transition-colors"
                        >
                            <FileText className="w-5 h-5"/> 
                            {t('actions.copy')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Notification Toast */}
            {notification && (
                <div className="fixed bottom-6 right-6 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg animate-fade-in z-50">
                    {notification}
                </div>
            )}
        </section>
    );
};

export default Hero;