import { Search, Share2, FileText, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { useState, useEffect } from "react";
import { useTranslation } from 'react-i18next';
import { copyToClipboard, shareContent } from '../utils/shareUtils';
import { verifyClaim } from "../services/api";
import Toast from './Toast';

const Hero = () => {
    const { t, i18n } = useTranslation();
    const [searchQuery, setSearchQuery] = useState('');
    const [toast, setToast] = useState(null);
    const [verificationResult, setVerificationResult] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [loadingStage, setLoadingStage] = useState('');
    const [cacheInfo, setCacheInfo] = useState(null);

    /**
     * 🆕 CACHE MANAGEMENT
     * Detect if result is from cache and if it needs refresh
     */
    useEffect(() => {
        if (verificationResult && verificationResult._from_cache) {
            setCacheInfo({
                isCached: true,
                timestamp: verificationResult.updated_at || verificationResult.created_at
            });
        } else {
            setCacheInfo(null);
        }
    }, [verificationResult]);

    /**
     * 🆕 FORCE REFRESH untuk bypass cache
     */
    const handleForceRefresh = async () => {
        if (!searchQuery.trim()) {
            showToast(t('hero.errors.emptyQuery'), 'warning');
            return;
        }

        setIsLoading(true);
        setError(null);
        setLoadingStage(t('hero.dynamicLabels.searching'));

        try {
            // Tambahkan timestamp untuk force refresh
            const result = await verifyClaim(searchQuery, { 
                force_refresh: true,
                timestamp: Date.now()
            });
            
            setVerificationResult(result);
            setCacheInfo(null);
            
            const label = formatLabel(result.verification_result?.label).text;
            showToast(`✓ ${t('hero.success.complete')} ${label}`, 'success');
            
        } catch (err) {
            console.error('Verification error:', err);
            const errorMessage = err.message || t('hero.errors.verificationFailed');
            setError(errorMessage);
            showToast(t('hero.errors.verificationFailed'), 'error');
        } finally {
            setIsLoading(false);
            setLoadingStage('');
        }
    };

    const showToast = (message, type = 'success') => { 
        setToast({ message, type });
    };

    const handleShare = async () => {
        const result = await shareContent({
            title: 'Healthify - ' + t('hero.desc'),
            text: generateShareText(verificationResult),
            url: window.location.href
        });
        
        if (result.success) {
            showToast(t('actions.shareSuccess'), 'success');
        } else {
            showToast(t('actions.shareFailed'), 'error');
        }
    };

    const handleCopy = async () => {
        if (!verificationResult) {
            showToast('No verification result to copy', 'warning');
            return;
        }

        const copyText = generateShareText(verificationResult);
        const result = await copyToClipboard(copyText);
        
        if (result.success) {
            showToast(t('actions.copied'), 'success');
        } else {
            showToast(t('actions.copyFailed'), 'error');
        }
    };

    const generateShareText = () => {
        if (!verificationResult) return '';

        const label = formatLabel(verificationResult.verification_result?.label).text;
        const confidence = formatConfidence(verificationResult.verification_result?.confidence || 0);
        const summary = verificationResult.verification_result?.summary || 'No summary available.';
        
        let text = `━━━━━━━━━━━━━━━━━━━━━━\n`;
        text += `🔍 HEALTHIFY - Health Claim Verification\n`;
        text += `━━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        text += `📋 ${t('hero.yourClaim')}:\n`;
        text += `"${verificationResult.text}"\n\n`;
        
        text += `🏷️ ${t('hero.analysisSummary')}: ${label}\n`;
        if (confidence) {
            text += `📊 ${t('hero.confidence')}: ${confidence}%\n\n`;
        }
        
        text += `📝 ${t('hero.analysisSummary')}:\n`;
        text += `${summary}\n\n`;
        
        if (verificationResult.sources && verificationResult.sources.length > 0) {
            text += `📚 ${t('hero.reference')}:\n`;
            verificationResult.sources.forEach((sourceItem, index) => {
                const source = sourceItem.source || {};
                const title = source.title || 'No Title Available';
                const doi = source.doi || '';
                const url = source.url || '';
                const relevanceScore = sourceItem.relevance_score || 0;
                
                text += `${index + 1}. ${title}`;
                if (doi) {
                    text += `\n   DOI: https://doi.org/${doi}`;
                } else if (url) {
                    text += `\n   URL: ${url}`;
                }
                if (relevanceScore > 0) {
                    text += `\n   ${t('hero.relevance')}: ${Math.round(relevanceScore * 100)}%`;
                }
                text += `\n`;
            });
            text += `\n`;
        }
        
        text += `━━━━━━━━━━━━━━━━━━━━━━\n`;
        text += `✅ ${t('hero.verifiedBy')}\n`;
        text += `📅 ${new Date(verificationResult.created_at).toLocaleDateString(i18n.language === 'id' ? 'id-ID' : 'en-US', {
            day: 'numeric',
            month: 'long',
            year: 'numeric'
        })}\n`;
        text += `🌐 Visit: https://healthify.app\n`;
        text += `━━━━━━━━━━━━━━━━━━━━━━\n`;
        
        return text;
    };

    const handleSearch = async (e) => {
        e.preventDefault();

        if (!searchQuery.trim()) {
            showToast(t('hero.errors.emptyQuery'), 'warning');
            return;
        }

        setIsLoading(true);
        setError(null);
        setVerificationResult(null);
        setLoadingStage(t('hero.dynamicLabels.analyzing'));

        try {
            // 🔧 Progress simulation untuk UX yang lebih baik
            setTimeout(() => setLoadingStage(t('hero.dynamicLabels.searching')), 3000);
            setTimeout(() => setLoadingStage(t('hero.dynamicLabels.evaluating')), 10000);
            setTimeout(() => setLoadingStage(t('hero.dynamicLabels.finalizing')), 20000);

            const result = await verifyClaim(searchQuery);
            setVerificationResult(result);
            
            const label = formatLabel(result.verification_result?.label).text;
            showToast(`✓ ${t('hero.success.complete')} ${label}`, 'success');
            
            console.log('Verification result:', result);
        } catch (err) {
            console.error('Verification error:', err);
            const errorMessage = err.message || t('hero.errors.verificationFailed');
            setError(errorMessage);
            showToast(t('hero.errors.verificationFailed'), 'error');
        } finally {
            setIsLoading(false);
            setLoadingStage('');
        }
    };

    const formatLabel = (label) => {
        if (!label) return { text: t('labels.unknown'), color: 'bg-gray-600' };
        
        const normalized = String(label).toLowerCase();
        const map = {
            'valid': { text: t('labels.valid'), color: 'bg-blue-600' },
            'hoax': { text: t('labels.hoax'), color: 'bg-red-600' },
            'uncertain': { text: t('labels.uncertain'), color: 'bg-orange-600' },
            'unverified': { text: t('labels.unverified'), color: 'bg-gray-600' }
        };
        
        return map[normalized] || { text: t('labels.unknown'), color: 'bg-gray-600' };
    };

    const formatConfidence = (confidence) => {
        if (confidence === null || confidence === undefined) return null;
        return Math.round(confidence * 100);
    };

    return (
        <section className="flex flex-col items-center max-w-4xl mx-auto text-center px-4 sm:px-6 lg:px-8">
            {/* Title */}
            <div className="mb-6 relative">
                <h1 className="text-3xl sm:text-4xl md:text-5xl text-gray-700 font-bold font-poppins">
                    {t('hero.title')}
                    <Search className="inline-block w-6 h-6 sm:w-8 sm:h-8 md:w-10 md:h-10 text-blue-400 ml-2 -mt-2 stroke-[3]"/>
                </h1>
            </div>
            <p className="text-slate-600 text-sm sm:text-base md:text-lg mb-8 max-w-2xl">
                {t('hero.subtitle')}
            </p>

            {/* Search Box */}
            <form onSubmit={handleSearch} className="w-full max-w-2xl bg-white p-2 rounded-full shadow-xl flex flex-col sm:flex-row items-center gap-2 sm:gap-0 mb-12 border border-slate-200">
                <input 
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('hero.searchPlaceholder')}
                    className="flex-1 w-full sm:w-auto px-4 sm:px-6 py-3 outline-none text-sm sm:text-base text-slate-700 placeholder:text-slate-400 bg-transparent"
                    disabled={isLoading}
                />
                <button 
                    type="submit"
                    disabled={isLoading}
                    className="w-full sm:w-auto bg-blue-500 hover:bg-blue-600 text-white px-6 md:px-8 py-3 rounded-full font-medium transition whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                    {isLoading ? (
                        <>
                            <Loader2 className="w-5 h-5 animate-spin" />
                            <span>{t('hero.verifying')}</span>
                        </>
                    ) : (
                        t('hero.verifyButton')
                    )}
                </button>
            </form>

            {/* 🆕 CACHE INFO BANNER */}
            {cacheInfo && cacheInfo.isCached && (
                <div className="w-full max-w-2xl mb-4 bg-blue-50 border border-blue-200 rounded-lg p-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm text-blue-800">
                        <AlertCircle className="w-4 h-4" />
                        <span>{t('hero.success.cached', { 
                            time: new Date(cacheInfo.timestamp).toLocaleString()
                        })}</span>
                    </div>
                    <button
                        onClick={handleForceRefresh}
                        disabled={isLoading}
                        className="flex items-center gap-1 text-blue-600 hover:text-blue-800 font-medium text-sm disabled:opacity-50"
                    >
                        <RefreshCw className="w-4 h-4" />
                        Refresh
                    </button>
                </div>
            )}

            {/* Error Message */}
            {error && (
                <div className="w-full max-w-2xl mb-6 bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                        <h4 className="font-semibold text-red-800 mb-1 text-sm sm:text-base">{t('common.error')}</h4>
                        <p className="text-xs sm:text-sm text-red-600 break-words">{error}</p>
                    </div>
                </div>
            )}

            {/* Loading Skeleton with Stage Info */}
            {isLoading && (
                <div className="w-full bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
                    <div className="h-2 bg-blue-500 w-full animate-pulse"></div>
                    <div className="p-4 sm:p-6 md:p-8 space-y-4">
                        <div className="text-center mb-4">
                            <Loader2 className="w-10 h-10 sm:w-12 sm:h-12 mx-auto text-blue-500 animate-spin mb-2" />
                            <p className="text-gray-600 font-medium text-sm sm:text-base">
                                {loadingStage || t('hero.analyzing')}
                            </p>
                            <p className="text-xs sm:text-sm text-gray-500 mt-1">{t('hero.pleaseWait')}</p>
                        </div>
                        <div className="h-6 sm:h-8 bg-gray-200 rounded animate-pulse"></div>
                        <div className="h-20 sm:h-24 bg-gray-200 rounded animate-pulse"></div>
                        <div className="h-14 sm:h-16 bg-gray-200 rounded animate-pulse"></div>
                    </div>
                </div>
            )}

            {/* Result Card */}
            {!isLoading && verificationResult && (
                <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden text-left relative w-full">
                    <div className="h-2 bg-blue-500 w-full"></div>
                    <div className="p-4 sm:p-6 md:p-8">
                        {/* Label Badge */}
                        {verificationResult.verification_result?.label && (
                            <span className={`${formatLabel(verificationResult.verification_result.label).color} text-white px-3 sm:px-4 py-1.5 rounded text-xs md:text-sm font-bold`}>
                                {formatLabel(verificationResult.verification_result.label).text}
                            </span>
                        )}
                        
                        {/* Confidence Badge */}
                        {verificationResult.verification_result?.confidence !== null &&
                         verificationResult.verification_result?.confidence !== undefined &&
                         verificationResult.verification_result?.label !== 'unverified' && (
                            <span className="bg-blue-100 text-blue-700 px-3 sm:px-4 py-1.5 rounded text-xs md:text-sm font-bold ml-2">
                                📊 {t('hero.confidence')}: {formatConfidence(verificationResult.verification_result.confidence)}%
                            </span>
                        )}
                        
                        {/* Claim Text */}
                        <div className="mb-4 mt-4 p-3 sm:p-4 bg-blue-50 rounded-lg">
                            <h3 className="font-bold text-sm sm:text-base text-slate-800 mb-2">{t('hero.yourClaim')}:</h3>
                            <p className="text-xs sm:text-sm text-slate-700 italic break-words">"{verificationResult.text}"</p>
                        </div>

                        {/* Summary */}
                        <div className="mb-6">
                            <h4 className="font-bold text-sm sm:text-base text-slate-800 mb-2">{t('hero.analysisSummary')}:</h4>
                            <p className="text-slate-600 leading-relaxed text-xs sm:text-sm md:text-base text-justify break-words">
                                {verificationResult.verification_result?.summary || t('hero.noSummary')}
                            </p>
                        </div>

                        {/* References */}
                        {verificationResult.sources && verificationResult.sources.length > 0 && (
                            <div className="mb-6">
                                <h4 className="font-bold text-sm sm:text-base text-slate-800 mb-2">{t('hero.reference')}</h4>
                                <ul className="text-xs sm:text-sm text-blue-500 space-y-2">
                                    {verificationResult.sources.map((sourceItem, index) => {
                                        const source = sourceItem.source || {};
                                        const doi = source.doi || '';
                                        const url = source.url || '';
                                        const title = source.title || '';
                                        const relevanceScore = sourceItem.relevance_score || 0;

                                        return (
                                            <li key={index} className="break-words">
                                                {doi ? (
                                                    <a 
                                                        href={`https://doi.org/${doi}`}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="underline hover:text-blue-700"
                                                    >
                                                        {index + 1}. {title || doi}
                                                        {relevanceScore > 0 && (
                                                            <span className="text-gray-500 ml-2 text-xs">
                                                                ({t('hero.relevance')}: {Math.round(relevanceScore * 100)}%)
                                                            </span>
                                                        )}
                                                    </a>
                                                ) : url ? (
                                                    <a 
                                                        href={url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="underline hover:text-blue-700"
                                                    >
                                                        {index + 1}. {title || url}
                                                    </a>
                                                ) : (
                                                    <span className="text-gray-700">
                                                        {index + 1}. {title || t('hero.noTitle')}
                                                    </span>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            </div>
                        )}

                        {/* Metadata */}
                        <div className="border-t border-gray-200 pt-4 mt-6">
                            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between text-xs text-gray-500 gap-2">
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold text-blue-600">{t('hero.verifiedBy')}</span>
                                </div>
                            </div>
                        </div>

                        {/* Action Buttons */}
                        <div className="flex flex-col sm:flex-row flex-wrap gap-3 sm:gap-4 justify-end text-xs sm:text-sm mt-4">
                            <button 
                                onClick={handleShare}
                                className="flex items-center justify-center gap-2 text-blue-500 hover:text-blue-700 transition-colors py-2 sm:py-0"
                            >
                                <Share2 className="w-4 h-4 sm:w-5 sm:h-5"/> 
                                {t('actions.share')}
                            </button>
                            <button 
                                onClick={handleCopy}
                                className="flex items-center justify-center gap-2 text-blue-500 hover:text-blue-700 transition-colors py-2 sm:py-0"
                            >
                                <FileText className="w-4 h-4 sm:w-5 sm:h-5"/> 
                                {t('actions.copy')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Placeholder */}
            {!isLoading && !verificationResult && !error && (
                <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden text-left relative w-full opacity-50">
                    <div className="h-2 bg-blue-500 w-full"></div>
                    <div className="p-4 sm:p-6 md:p-8">
                        <div className="text-center text-gray-500 py-8">
                            <Search className="w-12 h-12 sm:w-16 sm:h-16 mx-auto mb-4 text-gray-300"/>
                            <p className="text-base sm:text-lg font-medium">{t('hero.enterClaim')}</p>
                            <p className="text-xs sm:text-sm mt-2">{t('hero.resultsWillAppear')}</p>
                        </div>
                    </div>
                </div>
            )}

            {/* Toast */}
            {toast && (
                <Toast 
                    message={toast.message}
                    type={toast.type}
                    onClose={() => setToast(null)}
                />
            )}
        </section>
    );
};

export default Hero;