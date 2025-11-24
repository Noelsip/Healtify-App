import { Activity, AlertCircle, ArrowRight, BookOpen, Bot, Brain, CheckCircle, Clock, Cloud, Copy, Database, Download, Edit3, FileText, Filter, Globe, Layers, Monitor, Play, Save, Search, Share2, Sparkles, Target, Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const Documentation = () => {
  const { t } = useTranslation();

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8 text-left pb-10">
      {/* Title */}
      <section className="text-center mt-4 mb-4">
        <p className="text-xs sm:text-sm tracking-[0.3em] uppercase text-blue-500 mb-2">{t('documentation.header.label')}</p>
        <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-800">
          {t('documentation.header.title')}
        </h1>
        <p className="mt-3 text-xs sm:text-sm text-slate-600 max-w-2xl mx-auto">
          {t('documentation.header.subtitle')}
        </p>
      </section>

      {/* Apa itu Healthify */}
      <section className="bg-gradient-to-br from-blue-50 to-white rounded-2xl shadow-xl border border-slate-100 p-6 sm:p-8 space-y-6">
        <div className="text-center">
          <div className="inline-flex items-center gap-2 mb-3">
            <Activity className="w-8 h-8 sm:w-9 sm:h-9 text-blue-600" />
            <h2 className="text-xl sm:text-2xl font-bold text-gray-800">
              {t('documentation.about.title')}
            </h2>
          </div>
          <p className="text-base sm:text-lg text-slate-700 leading-relaxed max-w-3xl mx-auto">
            {t('documentation.about.intro')}
          </p>
        </div>

        {/* Key Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 my-6">
          <div className="bg-white rounded-xl p-4 border border-blue-100 shadow-sm text-center">
            <div className="flex justify-center mb-2">
              <Zap className="w-8 h-8 text-yellow-500" />
            </div>
            <p className="text-xs text-slate-600 uppercase tracking-wide mb-1">{t('hero.confidence')}</p>
            <p className="text-lg font-bold text-gray-800">{t('documentation.about.stats.speed')}</p>
          </div>
          <div className="bg-white rounded-xl p-4 border border-blue-100 shadow-sm text-center">
            <div className="flex justify-center mb-2">
              <BookOpen className="w-8 h-8 text-blue-600" />
            </div>
            <p className="text-xs text-slate-600 uppercase tracking-wide mb-1">{t('sources.title')}</p>
            <p className="text-lg font-bold text-gray-800">{t('documentation.about.stats.sources')}</p>
          </div>
          <div className="bg-white rounded-xl p-4 border border-blue-100 shadow-sm text-center">
            <div className="flex justify-center mb-2">
              <Bot className="w-8 h-8 text-purple-600" />
            </div>
            <p className="text-xs text-slate-600 uppercase tracking-wide mb-1">Technology</p>
            <p className="text-lg font-bold text-gray-800">{t('documentation.about.stats.tech')}</p>
          </div>
        </div>

        {/* Key Features */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="w-5 h-5 text-yellow-500" />
            <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.about.features.title')}</h3>
          </div>
          
          <div className="flex gap-3 items-start bg-white rounded-xl p-4 border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
            <Search className="w-6 h-6 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-slate-800 text-sm sm:text-base mb-1">{t('documentation.about.features.autoSearch.title')}</p>
              <p className="text-xs sm:text-sm text-slate-600">
                {t('documentation.about.features.autoSearch.desc')}
              </p>
            </div>
          </div>

          <div className="flex gap-3 items-start bg-white rounded-xl p-4 border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
            <Brain className="w-6 h-6 text-purple-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-slate-800 text-sm sm:text-base mb-1">{t('documentation.about.features.ragAI.title')}</p>
              <p className="text-xs sm:text-sm text-slate-600">
                {t('documentation.about.features.ragAI.desc')}
              </p>
            </div>
          </div>

          <div className="flex gap-3 items-start bg-white rounded-xl p-4 border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
            <CheckCircle className="w-6 h-6 text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-slate-800 text-sm sm:text-base mb-1">{t('documentation.about.features.transparent.title')}</p>
              <p className="text-xs sm:text-sm text-slate-600">
                {t('documentation.about.features.transparent.desc')}
              </p>
            </div>
          </div>

          <div className="flex gap-3 items-start bg-white rounded-xl p-4 border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
            <Globe className="w-6 h-6 text-blue-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-slate-800 text-sm sm:text-base mb-1">{t('documentation.about.features.multilang.title')}</p>
              <p className="text-xs sm:text-sm text-slate-600">
                {t('documentation.about.features.multilang.desc')}
              </p>
            </div>
          </div>
        </div>

        {/* Mission Statement */}
        <div className="bg-blue-600 text-white rounded-xl p-5 mt-6">
          <div className="flex items-start gap-3">
            <Target className="w-7 h-7 text-white flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-base sm:text-lg mb-2">{t('documentation.about.mission.title')}</p>
              <p className="text-xs sm:text-sm leading-relaxed">
                {t('documentation.about.mission.desc')}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Visual Pipeline */}
      <section className="space-y-6">
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-2xl shadow-xl p-6 sm:p-8 text-white">
          <div className="flex items-center gap-3 mb-3">
            <Bot className="w-8 h-8" />
            <h2 className="text-xl sm:text-2xl font-bold">{t('documentation.pipeline.title')}</h2>
          </div>
          <p className="text-sm sm:text-base opacity-90">
            {t('documentation.pipeline.subtitle')}
          </p>
        </div>

        {/* Fase 1: Data Acquisition */}
        <div className="bg-white rounded-2xl shadow-lg border border-blue-100 p-5 sm:p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-6 bg-blue-500 rounded-full"></div>
            <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.pipeline.phase1.title')}</h3>
            <span className="ml-auto text-xs text-blue-600 font-semibold">{t('documentation.pipeline.phase1.label')}</span>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gradient-to-br from-blue-50 to-white border border-blue-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Cloud className="w-6 h-6 text-blue-600" />
                <div>
                  <span className="text-xs font-bold text-blue-600">Step 1</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase1.step1.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase1.step1.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center">
              <ArrowRight className="w-5 h-5 text-blue-400" />
            </div>

            <div className="bg-gradient-to-br from-blue-50 to-white border border-blue-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Download className="w-6 h-6 text-blue-600" />
                <div>
                  <span className="text-xs font-bold text-blue-600">Step 2</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase1.step2.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase1.step2.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center md:col-span-1">
              <ArrowRight className="w-5 h-5 text-blue-400" />
            </div>

            <div className="bg-gradient-to-br from-blue-50 to-white border border-blue-100 rounded-xl p-4 hover:shadow-md transition-shadow md:col-start-2">
              <div className="flex items-center gap-2 mb-3">
                <div className="flex gap-1">
                  <FileText className="w-5 h-5 text-blue-600" />
                  <Filter className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <span className="text-xs font-bold text-blue-600">Step 3</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase1.step3.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase1.step3.desc')}
              </p>
            </div>
          </div>
        </div>

        {/* Fase 2: Processing & Indexing */}
        <div className="bg-white rounded-2xl shadow-lg border border-purple-100 p-5 sm:p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-6 bg-purple-500 rounded-full"></div>
            <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.pipeline.phase2.title')}</h3>
            <span className="ml-auto text-xs text-purple-600 font-semibold">{t('documentation.pipeline.phase2.label')}</span>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gradient-to-br from-purple-50 to-white border border-purple-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Layers className="w-6 h-6 text-purple-600" />
                <div>
                  <span className="text-xs font-bold text-purple-600">Step 4</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase2.step4.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase2.step4.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center">
              <ArrowRight className="w-5 h-5 text-purple-400" />
            </div>

            <div className="bg-gradient-to-br from-purple-50 to-white border border-purple-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-6 h-6 text-purple-600" />
                <div>
                  <span className="text-xs font-bold text-purple-600">Step 5</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase2.step5.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase2.step5.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center md:col-span-1">
              <ArrowRight className="w-5 h-5 text-purple-400" />
            </div>

            <div className="bg-gradient-to-br from-purple-50 to-white border border-purple-100 rounded-xl p-4 hover:shadow-md transition-shadow md:col-start-2">
              <div className="flex items-center gap-2 mb-3">
                <Database className="w-6 h-6 text-purple-600" />
                <div>
                  <span className="text-xs font-bold text-purple-600">Step 6</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase2.step6.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase2.step6.desc')}
              </p>
            </div>
          </div>
        </div>

        {/* Fase 3: Retrieval & Generation */}
        <div className="bg-white rounded-2xl shadow-lg border border-green-100 p-5 sm:p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-6 bg-green-500 rounded-full"></div>
            <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.pipeline.phase3.title')}</h3>
            <span className="ml-auto text-xs text-green-600 font-semibold">{t('documentation.pipeline.phase3.label')}</span>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gradient-to-br from-green-50 to-white border border-green-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Search className="w-6 h-6 text-green-600" />
                <div>
                  <span className="text-xs font-bold text-green-600">Step 7</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase3.step7.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase3.step7.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center">
              <ArrowRight className="w-5 h-5 text-green-400" />
            </div>

            <div className="bg-gradient-to-br from-green-50 to-white border border-green-100 rounded-xl p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center gap-2 mb-3">
                <Brain className="w-6 h-6 text-green-600" />
                <div>
                  <span className="text-xs font-bold text-green-600">Step 8</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase3.step8.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase3.step8.desc')}
              </p>
            </div>

            <div className="hidden md:flex items-center justify-center md:col-span-1">
              <ArrowRight className="w-5 h-5 text-green-400" />
            </div>

            <div className="bg-gradient-to-br from-green-50 to-white border border-green-100 rounded-xl p-4 hover:shadow-md transition-shadow md:col-start-2">
              <div className="flex items-center gap-2 mb-3">
                <div className="flex gap-1">
                  <Save className="w-5 h-5 text-green-600" />
                  <Monitor className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <span className="text-xs font-bold text-green-600">Step 9</span>
                  <p className="font-semibold text-slate-800 text-sm">{t('documentation.pipeline.phase3.step9.title')}</p>
                </div>
              </div>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.phase3.step9.desc')}
              </p>
            </div>
          </div>
        </div>

        {/* Translate pipeline */}
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex flex-col sm:flex-row gap-3 items-start sm:items-center">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-500 flex items-center justify-center">
              <Globe className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800 mb-0.5">{t('documentation.pipeline.translation.title')}</p>
              <p className="text-xs text-slate-600">
                {t('documentation.pipeline.translation.desc')}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* User Guide */}
      <section className="space-y-6">
        {/* Header */}
        <div className="bg-gradient-to-r from-green-600 to-teal-600 rounded-2xl shadow-xl p-6 sm:p-8 text-white">
          <div className="flex items-center gap-3 mb-3">
            <BookOpen className="w-8 h-8" />
            <h2 className="text-xl sm:text-2xl font-bold">{t('documentation.userGuide.title')}</h2>
          </div>
          <p className="text-sm sm:text-base opacity-90">
            {t('documentation.userGuide.subtitle')}
          </p>
        </div>

        <div className="space-y-4">
          {/* Step 1 */}
          <div className="bg-white rounded-xl shadow-lg border border-slate-100 p-5 sm:p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-md">
                  <Edit3 className="w-6 h-6 text-white" />
                </div>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs font-bold">Step 1</span>
                  <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.userGuide.step1.title')}</h3>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed mb-3">
                  {t('documentation.userGuide.step1.desc')}
                </p>
                <div className="bg-blue-50 border border-blue-100 rounded-lg p-3">
                  <p className="text-xs text-slate-700">
                    {t('documentation.userGuide.step1.example')}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2 */}
          <div className="bg-white rounded-xl shadow-lg border border-slate-100 p-5 sm:p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center shadow-md">
                  <Play className="w-6 h-6 text-white" />
                </div>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 text-xs font-bold">Step 2</span>
                  <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.userGuide.step2.title')}</h3>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed mb-3">
                  {t('documentation.userGuide.step2.desc')}
                </p>
                <button
                  type="button"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-500 text-white text-xs sm:text-sm font-medium shadow hover:bg-blue-600 transition-colors"
                  disabled
                >
                  <Play className="w-4 h-4" />
                  {t('documentation.userGuide.step2.button')}
                </button>
              </div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="bg-white rounded-xl shadow-lg border border-slate-100 p-5 sm:p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-yellow-500 to-orange-500 flex items-center justify-center shadow-md">
                  <Clock className="w-6 h-6 text-white" />
                </div>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 text-xs font-bold">Step 3</span>
                  <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.userGuide.step3.title')}</h3>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed mb-3">
                  {t('documentation.userGuide.step3.desc')}
                </p>
                <div className="bg-gradient-to-br from-slate-50 to-blue-50 border border-slate-200 rounded-xl p-4">
                  <p className="text-xs font-semibold text-slate-700 mb-3 flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600" />
                    {t('documentation.userGuide.step3.exampleTitle')}
                  </p>
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center px-3 py-1 text-xs font-bold rounded-full bg-red-500 text-white">
                        HOAX
                      </span>
                      <span className="inline-flex items-center px-3 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-700">
                        Confidence: 95%
                      </span>
                    </div>
                    <p className="text-xs text-slate-700 italic leading-relaxed">
                      "Klaim bahwa merokok tidak berbahaya bertentangan dengan bukti ilmiah yang ada. Merokok terbukti menyebabkan berbagai penyakit serius."
                    </p>
                    <div className="bg-white rounded-lg p-3 border border-blue-100">
                      <p className="text-xs font-semibold text-slate-700 mb-1">{t('documentation.userGuide.step3.exampleRef')}</p>
                      <a href="#" className="text-xs text-blue-600 hover:text-blue-800 underline">
                        📄 {t('documentation.userGuide.step3.exampleLink')}
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 4 */}
          <div className="bg-white rounded-xl shadow-lg border border-slate-100 p-5 sm:p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center shadow-md">
                  <Share2 className="w-6 h-6 text-white" />
                </div>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 text-xs font-bold">Step 4</span>
                  <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.userGuide.step4.title')}</h3>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed mb-3">
                  {t('documentation.userGuide.step4.desc')}
                </p>
                <div className="flex flex-wrap gap-3">
                  <button className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-50 border border-teal-200 text-teal-700 text-xs sm:text-sm font-medium hover:bg-teal-100 transition-colors">
                    <Share2 className="w-4 h-4" />
                    {t('documentation.userGuide.step4.shareBtn')}
                  </button>
                  <button className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-50 border border-teal-200 text-teal-700 text-xs sm:text-sm font-medium hover:bg-teal-100 transition-colors">
                    <Copy className="w-4 h-4" />
                    {t('documentation.userGuide.step4.copyBtn')}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Step 5 */}
          <div className="bg-white rounded-xl shadow-lg border border-slate-100 p-5 sm:p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-red-500 to-rose-600 flex items-center justify-center shadow-md">
                  <AlertCircle className="w-6 h-6 text-white" />
                </div>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-red-100 text-red-700 text-xs font-bold">Step 5</span>
                  <h3 className="text-base sm:text-lg font-bold text-gray-800">{t('documentation.userGuide.step5.title')}</h3>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed mb-3">
                  {t('documentation.userGuide.step5.desc')}
                </p>
                <button
                  type="button"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-red-500 text-white text-xs sm:text-sm font-medium shadow hover:bg-red-600 transition-colors"
                  disabled
                >
                  <AlertCircle className="w-4 h-4" />
                  {t('documentation.userGuide.step5.button')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default Documentation;
