import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  en: {
    translation: {
      nav: {
        home: "Home",
        about: "About",
        faq: "FAQ",
        contact: "Contact",
        documentation: "Documentation",
        report: "Report"
      },
      hero: {
        title: "Make Sure Your Information is Correct",
        subtitle: "Check health facts and avoid hoax news with one click",
        cta: "Get Started",
        desc: "Verify now",
        searchPlaceholder: "example: covid-19 causes infertility",
        verifyButton: "Verify Now",
        verifying: "Verifying...",
        analyzing: "Analyzing your claim...",
        pleaseWait: "This may take 30-60 seconds",
        yourClaim: "Your Claim",
        analysisSummary: "Analysis Summary",
        reference: "References",
        verifiedBy: "Verified by Healthify",
        confidence: "Confidence",
        relevance: "Relevance",
        noTitle: "No Title Available",
        noSummary: "No summary available",
        enterClaim: "Enter a claim to verify",
        resultsWillAppear: "Results will appear here after verification",
        errors: {
          emptyQuery: "Please enter a claim to verify",
          verificationFailed: "Verification failed. Please try again."
        },
        success: {
          complete: "Verification complete! Result:"
        }
      },
      labels: {
        valid: "FAKTA",
        hoax: "HOAX",
        uncertain: "TIDAK PASTI",
        unverified: "TIDAK TERVERIFIKASI",
        unknown: "Unknown"
      },
      common: {
        error: "Error",
        success: "Success",
        warning: "Warning",
        info: "Info"
      },
      faq: {
        title: "Frequently Asked Questions",
        questions: {
          q1: {
            question: "What is Healthify?",
            answer: "Healthify is a web-based application that helps you verify health claims or information using artificial intelligence (AI). This system analyzes the claims you input and matches them with trusted scientific sources such as PubMed journals, WHO, and CrossRef"
          },
          q2: {
            question: "Is Healthify free to use?",
            answer: "Yes, Healthify is free to use. You can verify health information at no cost."
          },
          q3: {
            question: "What data sources does Healthify use?",
            answer: "Healthify only uses credible and verified sources, such as: PubMed, CrossRef, Semantic Scholar, Elsevier, Google Books, NCBI"
          },
          q4: {
            question: "Can Healthify's results be used as medical references?",
            answer: "No. Healthify is not a medical diagnostic tool, but an educational aid to check the accuracy of health information based on scientific literature. For medical decisions, always consult with professional healthcare providers."
          },
          q5: {
            question: "What if I find incorrect results?",
            answer: "You can press the 'Report Error' (Dispute) button on the results page. Fill in the reason and, if available, include a link to an alternative evidence source. The Healthify team will review your report."
          }
        }
      },
      sources: {
        title: "Sources"
      },
      footer: {
        title: "Healthify",
        learnMore: "Learn More",
        about: "About",
        documentation: "Documentation",
        report: "Report",
        contact: "Contact Us",
        copyright: "© 2025 Healthify | Informatics, Kalimantan Institute of Technology",
        privacyPolicy: "Privacy Policy",
        termsOfService: "Terms of Service"
      },
      actions: {
        copy: "Copy",
        share: "Share",
        copied: "Copied!",
        copyFailed: "Failed to copy",
        shareSuccess: "Shared successfully",
        shareFailed: "Failed to share"
      },
      language: {
        id: "ID",
        en: "EN",
        toggle: "ID / EN"
      }
    }
  },
  id: {
    translation: {
      nav: {
        home: "Beranda",
        about: "Tentang",
        faq: "FAQ",
        contact: "Kontak",
        documentation: "Dokumentasi",
        report: "Laporkan"
      },
      hero: {
        title: "Yakin Informasi Kamu Benar",
        subtitle: "Cek fakta kesehatan dan hindari berita hoax dengan satu klik",
        cta: "Mulai Sekarang",
        desc: "Verifikasi sekarang",
        searchPlaceholder: "contoh: covid-19 membuat kemandulan",
        verifyButton: "Verifikasi Sekarang",
        verifying: "Memverifikasi...",
        analyzing: "Menganalisis klaim Anda...",
        pleaseWait: "Ini mungkin memakan waktu 30-60 detik",
        yourClaim: "Klaim Anda",
        analysisSummary: "Ringkasan Analisis",
        reference: "Referensi",
        verifiedBy: "Diverifikasi oleh Healthify",
        confidence: "Tingkat Keyakinan",
        relevance: "Relevansi",
        noTitle: "Tidak Ada Judul",
        noSummary: "Tidak ada ringkasan tersedia",
        enterClaim: "Masukkan klaim untuk diverifikasi",
        resultsWillAppear: "Hasil akan muncul di sini setelah verifikasi",
        errors: {
          emptyQuery: "Silakan masukkan klaim untuk diverifikasi",
          verificationFailed: "Verifikasi gagal. Silakan coba lagi."
        },
        success: {
          complete: "Verifikasi selesai! Hasil:"
        }
      },
      labels: {
        valid: "FAKTA",
        hoax: "HOAX",
        uncertain: "TIDAK PASTI",
        unverified: "TIDAK TERVERIFIKASI",
        unknown: "Tidak Diketahui"
      },
      common: {
        error: "Kesalahan",
        success: "Berhasil",
        warning: "Peringatan",
        info: "Informasi"
      },
      faq: {
        title: "Pertanyaan yang Sering Diajukan",
        questions: {
          q1: {
            question: "Apa itu Healthify?",
            answer: "Healthify adalah aplikasi berbasis web yang membantu kamu memverifikasi klaim atau informasi kesehatan menggunakan kecerdasan buatan (AI). Sistem ini menganalisis klaim yang kamu masukkan dan mencocokkannya dengan sumber ilmiah terpercaya seperti jurnal PubMed, WHO, dan CrossRef"
          },
          q2: {
            question: "Apakah Healthify gratis digunakan?",
            answer: "Ya, Healthify gratis untuk digunakan. Kamu dapat memverifikasi informasi kesehatan tanpa biaya apapun."
          },
          q3: {
            question: "Sumber data apa yang digunakan oleh Healthify?",
            answer: "Healthify hanya menggunakan sumber kredibel dan terverifikasi, seperti: PubMed, CrossRef, Semantic Scholar, Elsevier, Google Books, NCBI"
          },
          q4: {
            question: "Apakah hasil dari Healthify bisa dijadikan rujukan medis?",
            answer: "Tidak. Healthify bukan alat diagnosis medis, melainkan alat bantu edukatif untuk memeriksa kebenaran informasi kesehatan berdasarkan literatur ilmiah. Untuk keputusan medis, selalu konsultasikan dengan tenaga kesehatan profesional."
          },
          q5: {
            question: "Bagaimana jika saya menemukan hasil yang salah?",
            answer: "Kamu dapat menekan tombol 'Laporkan Kesalahan' (Dispute) di halaman hasil. Isi alasan dan, bila ada, sertakan tautan ke sumber bukti alternatif. Tim Healthify akan meninjau laporanmu."
          }
        }
      },
      sources: {
        title: "Sumber"
      },
      footer: {
        title: "Healthify",
        learnMore: "Pelajari Lebih Lanjut",
        about: "Tentang",
        documentation: "Dokumentasi",
        report: "Laporkan",
        contact: "Hubungi Kami",
        copyright: "© 2025 Healthify | Informatika Institut Teknologi Kalimantan",
        privacyPolicy: "Kebijakan Privasi",
        termsOfService: "Syarat Layanan"
      },
      actions: {
        copy: "Salin",
        share: "Bagikan",
        copied: "Tersalin!",
        copyFailed: "Gagal menyalin",
        shareSuccess: "Berhasil dibagikan",
        shareFailed: "Gagal membagikan"
      },
      language: {
        id: "ID",
        en: "EN",
        toggle: "ID / EN"
      }
    }
  }
};

i18n
  .use(initReactI18next)
  .init({
    resources,
    lng: 'id',
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false
    },
    react: {
      useSuspense: false
    }
  });

export default i18n;