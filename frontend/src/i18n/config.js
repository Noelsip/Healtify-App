import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const resources = {
  en: {
    translation: {
      common: {
        error: "Error",
        success: "Success",
        loading: "Loading...",
        submit: "Submit",
        cancel: "Cancel",
        close: "Close",
        save: "Save"
      },
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
      // REPORT PAGE TRANSLATIONS
      report: {
        title: "Report Verification Error",
        claimLabel: "Reported Claim",
        claimPlaceholder: "Copy and paste the claim you want to report here...",
        reasonLabel: "Explain why you think the verification result is incorrect (ideally based on the journal abstract if you provide a DOI)",
        reasonPlaceholder: "Explain in detail which part of the result is not consistent with the journal abstract or other evidence you have...",
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
        doiHelper: "Enter a DOI link from a scientific journal and, if possible, base your explanation on its abstract",
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
        },
        validation: {
          invalidFormat: "Invalid file format. Only PDF files are allowed.",
          fileTooLarge: "File size too large. Maximum 20MB.",
          claimRequired: "Claim is required",
          reasonRequired: "Reason is required",
          doiRequired: "DOI link is required",
          fileRequired: "PDF file must be uploaded"
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
      },
      documentation: {
        header: {
          label: "Documentation",
          title: "Healthify Documentation",
          subtitle: "Learn how Healthify works behind the scenes and how you can use it to verify health claims quickly and accurately."
        },
        about: {
          title: "What is Healthify?",
          intro: "AI assistant that helps you verify health claims in seconds, not based on opinions, but based on thousands of scientific publications.",
          stats: {
            speed: "Seconds, not days",
            sources: "5+ scientific APIs",
            tech: "AI + RAG"
          },
          features: {
            title: "Why is Healthify Different?",
            autoSearch: {
              title: "Automatic Evidence Search",
              desc: "The system searches and analyzes publications from PubMed, Semantic Scholar, CrossRef, Elsevier, and Google Books automatically—you don't need to do manual research."
            },
            ragAI: {
              title: "AI with Scientific Context (RAG)",
              desc: "Uses Retrieval-Augmented Generation (RAG) so the LLM doesn't just \"guess\", but answers based on concrete evidence from the vector database."
            },
            transparent: {
              title: "Structured & Transparent Results",
              desc: "Every verification comes with a label (Valid/Hoax/Uncertain), confidence score, summary, and list of references you can check yourself."
            },
            multilang: {
              title: "Multilingual & Easy Access",
              desc: "Supports Indonesian and English. Just type a claim, click the button, and get the answer—no registration or subscription required."
            }
          },
          mission: {
            title: "Our Mission",
            desc: "Help Indonesian and global communities be more critical of circulating health information, reduce hoax spread, and improve data-based scientific literacy—not just viral on social media."
          }
        },
        pipeline: {
          title: "Architecture (Pipeline)",
          subtitle: "The following pipeline shows how Healthify builds a knowledge base and answers claims. The main source comes from external APIs like PubMed, Google Books, Semantic Scholar, and others.",
          phase1: {
            title: "Phase 1: Data Acquisition",
            label: "Data Collection",
            step1: { title: "API Sources", desc: "Scientific data from PubMed, Google Books, Semantic Scholar, etc." },
            step2: { title: "Ingestion", desc: "Collect & store structured data, prepare consistent format." },
            step3: { title: "Extract & Normalize", desc: "Extract important content, normalize text (lowercase, cleaning)." }
          },
          phase2: {
            title: "Phase 2: Processing & Indexing",
            label: "Data Processing",
            step4: { title: "Word Chunking", desc: "Split text into short chunks based on words/sentences." },
            step5: { title: "Batch Embedding", desc: "Create vector embeddings with Gemini (batch mode)." },
            step6: { title: "pgvector (Postgres)", desc: "Store embeddings in pgvector for similarity search." }
          },
          phase3: {
            title: "Phase 3: Retrieval & Generation",
            label: "Verification & Output",
            step7: { title: "Retriever", desc: "Find the most relevant chunks from pgvector based on user claim." },
            step8: { title: "LLM (RAG)", desc: "LLM analyzes claim based on evidence (RAG)." },
            step9: { title: "Result & Frontend", desc: "Store as VerificationResult, display in UI." }
          },
          translation: {
            title: "Translation Layer",
            desc: "Verification results can be translated to Indonesian or English via the /api/translate/ endpoint, so claim and summary displays follow UI language."
          }
        },
        userGuide: {
          title: "How to Use the App",
          subtitle: "Step-by-step guide to verify health claims using Healthify. The process is fast, easy, and requires no registration.",
          step1: {
            title: "Enter Claim",
            desc: "Type the health statement you want to check in the \"Enter Claim\" field on the homepage.",
            example: "Example: \"Drinking lemon water can cure the flu\""
          },
          step2: {
            title: "Press Check Button",
            desc: "Click the \"Verify Now\" button. The AI system will start searching for scientific evidence related to that claim.",
            button: "Verify Now"
          },
          step3: {
            title: "Wait for Verification Results",
            desc: "Healthify will display the claim status (Valid / Hoax / Uncertain), confidence level, and list of scientific references in seconds.",
            exampleTitle: "Example Display Result:",
            exampleRef: "References:",
            exampleLink: "\"Health risks of smoking\" - PubMed (2023)"
          },
          step4: {
            title: "Share Information",
            desc: "You can share verification results with others using the share or copy buttons available on the result card.",
            shareBtn: "Share",
            copyBtn: "Copy"
          },
          step5: {
            title: "Report if There's an Error",
            desc: "Please report if you find verification results that feel incorrect based on other scientific evidence you have, via the \"Report\" page.",
            button: "Report"
          }
        }
      }
    }
  },
  id: {
    translation: {
      common: {
        error: "Error",
        success: "Berhasil",
        loading: "Memuat...",
        submit: "Kirim",
        cancel: "Batal",
        close: "Tutup",
        save: "Simpan"
      },
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
        reasonLabel: "Jelaskan mengapa hasil verifikasi menurut Anda salah (sebaiknya berdasarkan abstrak jurnal jika Anda mengisi DOI)",
        reasonPlaceholder: "Jelaskan secara rinci bagian mana dari hasil verifikasi yang tidak sesuai dengan abstrak jurnal atau bukti lain yang Anda punya...",
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
        doiHelper: "Masukan Link DOI dari jurnal ilmiah dan, jika bisa, dasarkan alasan Anda pada abstrak jurnal tersebut",
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
        },
        validation: {
          invalidFormat: "Format file tidak valid. Hanya file PDF yang diperbolehkan.",
          fileTooLarge: "Ukuran file terlalu besar. Maksimal 20MB.",
          claimRequired: "Klaim harus diisi",
          reasonRequired: "Alasan harus diisi",
          doiRequired: "Link DOI harus diisi",
          fileRequired: "File PDF harus diunggah"
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
      },
      documentation: {
        header: {
          label: "Documentation",
          title: "Dokumentasi Healthify",
          subtitle: "Pelajari bagaimana Healthify bekerja di balik layar dan bagaimana kamu bisa memanfaatkannya untuk memverifikasi klaim kesehatan dengan cepat dan akurat."
        },
        about: {
          title: "Apa itu Healthify?",
          intro: "Asisten AI yang membantu kamu memverifikasi klaim kesehatan dalam hitungan detik, bukan berdasarkan opini, tapi berdasarkan ribuan publikasi ilmiah.",
          stats: {
            speed: "Detik, bukan hari",
            sources: "5+ API ilmiah",
            tech: "AI + RAG"
          },
          features: {
            title: "Kenapa Healthify Berbeda?",
            autoSearch: {
              title: "Pencarian Bukti Otomatis",
              desc: "Sistem mencari dan menganalisis publikasi dari PubMed, Semantic Scholar, CrossRef, Elsevier, dan Google Books secara otomatis—kamu tidak perlu riset manual."
            },
            ragAI: {
              title: "AI dengan Konteks Ilmiah (RAG)",
              desc: "Menggunakan Retrieval-Augmented Generation (RAG) sehingga LLM tidak hanya \"menebak\", tapi menjawab berdasarkan bukti konkret dari database vektor."
            },
            transparent: {
              title: "Hasil Terstruktur & Transparan",
              desc: "Setiap verifikasi dilengkapi dengan label (Valid/Hoax/Tidak Pasti), skor kepercayaan, ringkasan, dan daftar referensi yang bisa kamu cek sendiri."
            },
            multilang: {
              title: "Multibahasa & Mudah Diakses",
              desc: "Mendukung Bahasa Indonesia dan Inggris. Cukup ketik klaim, klik tombol, dan dapatkan jawaban—tidak perlu registrasi atau langganan."
            }
          },
          mission: {
            title: "Misi Kami",
            desc: "Membantu masyarakat Indonesia dan dunia lebih kritis terhadap informasi kesehatan yang beredar, menurunkan penyebaran hoaks, dan meningkatkan literasi sains berbasis data—bukan sekadar viral di media sosial."
          }
        },
        pipeline: {
          title: "Arsitektur Singkat (Pipeline)",
          subtitle: "Pipeline berikut menggambarkan bagaimana Healthify membangun basis pengetahuan dan menjawab klaim. Sumber utama berasal dari API eksternal seperti PubMed, Google Books, Semantic Scholar, dan lain-lain.",
          phase1: {
            title: "Fase 1: Data Acquisition",
            label: "Pengumpulan Data",
            step1: { title: "API Sources", desc: "Data ilmiah dari PubMed, Google Books, Semantic Scholar, dll." },
            step2: { title: "Ingestion", desc: "Kumpulkan & simpan terstruktur, siapkan format konsisten." },
            step3: { title: "Extract & Normalize", desc: "Ekstrak konten penting, normalisasi teks (lowercase, cleaning)." }
          },
          phase2: {
            title: "Fase 2: Processing & Indexing",
            label: "Pemrosesan Data",
            step4: { title: "Word Chunking", desc: "Pecah teks jadi chunk pendek berbasis kata/kalimat." },
            step5: { title: "Batch Embedding", desc: "Buat embedding vektor dengan Gemini (batch mode)." },
            step6: { title: "pgvector (Postgres)", desc: "Simpan embedding di pgvector untuk similarity search." }
          },
          phase3: {
            title: "Fase 3: Retrieval & Generation",
            label: "Verifikasi & Output",
            step7: { title: "Retriever", desc: "Cari chunk paling relevan dari pgvector berdasarkan klaim user." },
            step8: { title: "LLM (RAG)", desc: "LLM analisis klaim berdasarkan bukti (RAG)." },
            step9: { title: "Result & Frontend", desc: "Simpan sebagai VerificationResult, tampilkan di UI." }
          },
          translation: {
            title: "Layer Terjemahan",
            desc: "Hasil verifikasi dapat diterjemahkan ke bahasa Indonesia atau Inggris melalui endpoint /api/translate/, sehingga tampilan klaim dan ringkasan mengikuti bahasa UI."
          }
        },
        userGuide: {
          title: "Cara Penggunaan Aplikasi",
          subtitle: "Panduan langkah demi langkah untuk memverifikasi klaim kesehatan menggunakan Healthify. Prosesnya cepat, mudah, dan tidak memerlukan registrasi.",
          step1: {
            title: "Masukkan Klaim",
            desc: "Ketik pernyataan kesehatan yang ingin kamu periksa di kolom \"Masukkan Klaim\" di halaman utama.",
            example: "Contoh: \"Minum air lemon bisa menyembuhkan flu\""
          },
          step2: {
            title: "Tekan Tombol Periksa",
            desc: "Klik tombol \"Verifikasi Sekarang\". Sistem AI akan mulai mencari bukti ilmiah terkait klaim tersebut.",
            button: "Verifikasi Sekarang"
          },
          step3: {
            title: "Tunggu Hasil Verifikasi",
            desc: "Healthify akan menampilkan status klaim (Valid / Hoax / Tidak Pasti), tingkat kepercayaan, serta daftar referensi ilmiah dalam hitungan detik.",
            exampleTitle: "Contoh Tampilan Hasil:",
            exampleRef: "Referensi:",
            exampleLink: "\"Health risks of smoking\" - PubMed (2023)"
          },
          step4: {
            title: "Bagikan Informasi",
            desc: "Anda bisa menyebarkan hasil verifikasi kepada orang lain melalui tombol bagikan atau salin yang tersedia di kartu hasil.",
            shareBtn: "Bagikan",
            copyBtn: "Salin"
          },
          step5: {
            title: "Laporkan Jika Ada Kesalahan",
            desc: "Silakan laporkan jika kamu menemukan hasil verifikasi yang terasa keliru berdasarkan bukti ilmiah lain yang kamu miliki, melalui halaman \"Laporkan\".",
            button: "Laporkan"
          }
        }
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