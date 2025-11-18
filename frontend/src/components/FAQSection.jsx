import { useState } from "react";
import { ChevronDown } from "react-feather";
import { useTranslation } from 'react-i18next';

const FAQItem = ({ question, answer }) => {
    const [isOpen, setIsOpen] = useState(false);

    return (
        <div className="bg-blue-50/50 rounded-lg overflow-hidden transition-all hover:shadow-md">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full px-6 py-4 flex items-center justify-between text-left font-poppins font-semibold text-slate-700 hover:bg-blue-100/50 transition"
            >
                <span className="pr-4">{question}</span>
                <ChevronDown 
                    className={`w-5 h-5 flex-shrink-0 transition-transform duration-300 ${
                        isOpen ? 'rotate-180' : ''
                    }`} 
                />
            </button>

            <div 
                className={`grid transition-all duration-300 ease-in-out ${
                    isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
                }`}
            >
                <div className="overflow-hidden">
                    <div className="px-6 py-4 text-slate-600 text-sm bg-blue-50/30">
                        {answer}
                    </div>
                </div>
            </div>
        </div>
    );
};

const FAQSection = () => {
    const { t } = useTranslation();
    
    // Gunakan data dari i18n
    const faqs = [
        {
            question: t('faq.questions.q1.question'),
            answer: t('faq.questions.q1.answer')
        },
        {
            question: t('faq.questions.q2.question'),
            answer: t('faq.questions.q2.answer')
        },
        {
            question: t('faq.questions.q3.question'),
            answer: t('faq.questions.q3.answer')
        },
        {
            question: t('faq.questions.q4.question'),
            answer: t('faq.questions.q4.answer')
        },
        {
            question: t('faq.questions.q5.question'),
            answer: t('faq.questions.q5.answer')
        }
    ];

    return (
        <section className="max-w-3xl mx-auto px-4">
            <div className="bg-white rounded-3xl shadow-xl p-6 md:p-10">
                <h2 className="text-2xl md:text-3xl font-bold text-center text-slate-800 mb-8">
                    {t('faq.title')}
                </h2>
                <div className="space-y-3">
                    {faqs.map((faq, idx) => (
                        <FAQItem key={idx} question={faq.question} answer={faq.answer} />
                    ))}
                </div>
            </div>
        </section>
    );
};

export default FAQSection;