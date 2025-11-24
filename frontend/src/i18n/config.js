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
          verificationFailed: "Verification failed. Please try again.",
          networkError: "Network error. Check your connection.",
          timeout: "Request timeout. Please try again."
        },
        success: {
          complete: "Verification complete! Result:",
          cached: "Using cached result (updated: {time})"
        },
        // 🆕 DYNAMIC CONTENT TRANSLATIONS
        dynamicLabels: {
          analyzing: "Analyzing claim...",
          searching: "Searching scientific databases...",
          evaluating: "Evaluating evidence...",
          finalizing: "Finalizing results..."
        }
      },
      labels: {
        valid: "FACT",
        hoax: "HOAX",
        uncertain: "UNCERTAIN",
        unverified: "UNVERIFIED",
        unknown: "Unknown",
        // 🆕 DETAILED EXPLANATIONS
        explanations: {
          valid: "This claim is supported by scientific evidence",
          hoax: "This claim contradicts scientific evidence",
          uncertain: "This claim is partially true or context-dependent",
          unverified: "Insufficient evidence to verify this claim"
        }
      },
      common: {
        error: "Error",
        success: "Success",
        warning: "Warning",
        info: "Info",
        loading: "Loading...",
        retry: "Retry",
        cancel: "Cancel",
        submit: "Submit"
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
      // 🆕 REPORT PAGE TRANSLATIONS
      report: {
        title: "Report Verification Error",
        claimLabel: "Reported Claim",
        claimPlaceholder: "Copy and paste the claim you want to report here...",
        reasonLabel: "Explain why you think the verification result is incorrect",
        reasonPlaceholder: "Detailed explanation of discrepancy...",
        reporterInfo: "Reporter Information (Optional)",
        name: "Name",
        namePlaceholder: "Your Name",
        email: "Email",
        emailPlaceholder: "email@example.com",
        supportingEvidence: "Supporting Evidence",
        evidenceTypes: {
          doi: "DOI Link",
          pdf: "Upload PDF File"
        },
        doiLabel: "DOI Link",
        doiPlaceholder: "https://doi.org/10.xxxx/xxxxx",
        doiHelper: "Enter DOI link from scientific journal supporting your claim",
        pdfLabel: "Upload PDF File",
        pdfHelper: "Maximum file size: 20MB",
        urlLabel: "Source Link (Optional)",
        urlPlaceholder: "https://example.com/article",
        submitButton: "Submit Report",
        submitting: "Submitting Report...",
        note: {
          title: "Note:",
          content: "The Healthify team will review your report and verify the evidence provided. This process may take 1-3 business days. Thank you for contributing to improving Healthify's accuracy."
        },
        success: {
          title: "Report Successfully Submitted!",
          message: "Thank you for your contribution. The Healthify team will review your report within 1-3 business days."
        },
        errors: {
          emptyFile: "Please select a file",
          invalidFormat: "File must be in PDF format",
          fileTooLarge: "File size exceeds maximum (20MB)",
          submitFailed: "Failed to submit report. Please try again."
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
        toggle: "ID / EN",
        current: "Current Language: English"
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
          verificationFailed: "Verifikasi gagal. Silakan coba lagi.",
          networkError: "Kesalahan jaringan. Periksa koneksi Anda.",
          timeout: "Waktu permintaan habis. Silakan coba lagi."
        },
        success: {
          complete: "Verifikasi selesai! Hasil:",
          cached: "Menggunakan hasil cache (diperbarui: {time})"
        },
        dynamicLabels: {
          analyzing: "Menganalisis klaim...",
          searching: "Mencari database ilmiah...",
          evaluating: "Mengevaluasi bukti...",
          finalizing: "Menyelesaikan hasil..."
        }
      },
      labels: {
        valid: "FAKTA",
        hoax: "HOAX",
        uncertain: "TIDAK PASTI",
        unverified: "TIDAK TERVERIFIKASI",
        unknown: "Tidak Diketahui",
        explanations: {
          valid: "Klaim ini didukung oleh bukti ilmiah",
          hoax: "Klaim ini bertentangan dengan bukti ilmiah",
          uncertain: "Klaim ini sebagian benar atau tergantung konteks",
          unverified: "Bukti tidak cukup untuk memverifikasi klaim ini"
        }
      },
      common: {
        error: "Kesalahan",
        success: "Berhasil",
        warning: "Peringatan",
        info: "Informasi",
        loading: "Memuat...",
        retry: "Coba Lagi",
        cancel: "Batal",
        submit: "Kirim"
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
      report: {
        title: "Laporkan Kesalahan Klaim",
        claimLabel: "Klaim yang Dilaporkan",
        claimPlaceholder: "Salin dan tempel klaim yang ingin Anda laporkan disini...",
        reasonLabel: "Jelaskan mengapa hasil verifikasi menurut Anda salah",
        reasonPlaceholder: "Detail alasan ketidaksesuaian...",
        reporterInfo: "Informasi Pelapor (Opsional)",
        name: "Nama",
        namePlaceholder: "Nama Anda",
        email: "Email",
        emailPlaceholder: "email@example.com",
        supportingEvidence: "Bukti Pendukung",
        evidenceTypes: {
          doi: "Link DOI",
          pdf: "Upload File PDF"
        },
        doiLabel: "Link DOI",
        doiPlaceholder: "https://doi.org/10.xxxx/xxxxx",
        doiHelper: "Masukan Link DOI dari jurnal ilmiah yang mendukung klaim Anda",
        pdfLabel: "Upload File PDF",
        pdfHelper: "Maksimal ukuran file: 20MB",
        urlLabel: "Link Sumber (Opsional)",
        urlPlaceholder: "https://example.com/artikel",
        submitButton: "Kirim Laporan",
        submitting: "Mengirim Laporan...",
        note: {
          title: "Catatan:",
          content: "Tim Healthify akan meninjau laporan Anda dan melakukan verifikasi terhadap bukti yang diberikan. Proses ini dapat memakan waktu 1-3 hari kerja. Terima kasih atas kontribusi Anda dalam meningkatkan akurasi Healthify."
        },
        success: {
          title: "Laporan Berhasil Dikirim!",
          message: "Terima kasih atas kontribusi Anda. Tim Healthify akan meninjau laporan Anda dalam 1-3 hari kerja."
        },
        errors: {
          emptyFile: "Silakan pilih file",
          invalidFormat: "File harus berformat PDF",
          fileTooLarge: "Ukuran file melebihi maksimal (20MB)",
          submitFailed: "Gagal mengirim laporan. Silakan coba lagi."
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
        toggle: "ID / EN",
        current: "Bahasa Saat Ini: Indonesia"
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