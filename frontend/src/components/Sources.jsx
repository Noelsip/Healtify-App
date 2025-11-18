import React from 'react';
import { useTranslation } from 'react-i18next';
import googleBooksLogo from '../assets/google-books.png';
import ncbiLogo from '../assets/ncbi.png';
import crossrefLogo from '../assets/crossref.png';
import semanticLogo from '../assets/semantic.png';
import elsevierLogo from '../assets/elsevier.png';

const Sources = () => {
    const { t } = useTranslation();
    
    const sources = [
        { logo: googleBooksLogo},
        { logo: ncbiLogo },
        { logo: crossrefLogo },
        { logo: semanticLogo },
        { logo: elsevierLogo }
    ];

    return (
        <section className="py-12 overflow-hidden px-4">
            <h3 className="text-2xl md:text-3xl font-bold text-center text-slate-800 mb-8">
                {t('sources.title')}
            </h3>
            <div className="relative">
                <div className="flex animate-marquee">
                    {/* First set */}
                    {sources.map((source, idx) => (
                        <div 
                            key={`first-${idx}`} 
                            className="flex flex-col items-center gap-3 p-6 min-w-[150px] mx-4"
                        >
                            <img 
                                src={source.logo} 
                                alt={`${source.name} logo`}
                                className="w-16 h-16 object-contain hover:scale-110 transition-transform"
                            />
                            <span className="text-sm font-semibold text-slate-600 text-center whitespace-nowrap">
                                {source.name}
                            </span>
                        </div>
                    ))}
                    {/* Duplicate set for seamless loop */}
                    {sources.map((source, idx) => (
                        <div 
                            key={`second-${idx}`} 
                            className="flex flex-col items-center gap-3 p-6 min-w-[150px] mx-4"
                        >
                            <img 
                                src={source.logo} 
                                alt={`${source.name} logo`}
                                className="w-16 h-16 object-contain hover:scale-110 transition-transform"
                            />
                            <span className="text-sm font-semibold text-slate-600 text-center whitespace-nowrap">
                                {source.name}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
};

export default Sources;