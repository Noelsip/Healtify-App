import React, { useState } from "react";
import { AlertCircle, CheckCircle, Upload, Loader2 } from 'lucide-react';
import { createDispute } from '../services/api';

const Report = () => {
    // State untuk form fields
    const [formData, setFormData] = useState({
        claim_text: '',
        reason: '',
        reporter_name: '',
        reporter_email: '',
        supporting_doi: '',
        supporting_url: '',
        supporting_file: null
    });
    
    // State untuk UI
    const [buktiType, setBuktiType] = useState('doi_link');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitStatus, setSubmitStatus] = useState(null); // 'success' | 'error' | null
    const [errorMessage, setErrorMessage] = useState('');

    // Handle input change
    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: value
        }));
    };

    // Handle file upload
    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (file) {
            // Validasi file PDF
            if (file.type !== 'application/pdf') {
                setErrorMessage('File harus berformat PDF');
                e.target.value = null;
                return;
            }
            // Validasi ukuran file (max 20MB)
            if (file.size > 20 * 1024 * 1024) {
                setErrorMessage('Ukuran file maksimal 20MB');
                e.target.value = null;
                return;
            }
            setFormData(prev => ({
                ...prev,
                supporting_file: file
            }));
            setErrorMessage('');
        }
    };

    // Handle radio button change
    const handleBuktiTypeChange = (type) => {
        setBuktiType(type);
        // Reset supporting data based on type
        if (type === 'doi_link') {
            setFormData(prev => ({
                ...prev,
                supporting_file: null,
                supporting_url: ''
            }));
        } else {
            setFormData(prev => ({
                ...prev,
                supporting_doi: ''
            }));
        }
    };

    // Validasi form
    const validateForm = () => {
        if (!formData.claim_text.trim()) {
            setErrorMessage('Klaim harus diisi');
            return false;
        }
        if (!formData.reason.trim()) {
            setErrorMessage('Alasan harus diisi');
            return false;
        }
        if (buktiType === 'doi_link' && !formData.supporting_doi.trim()) {
            setErrorMessage('Link DOI harus diisi');
            return false;
        }
        if (buktiType === 'upload_pdf' && !formData.supporting_file) {
            setErrorMessage('File PDF harus diunggah');
            return false;
        }
        return true;
    };

    // Handle form submit
    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMessage('');
        setSubmitStatus(null);

        // Validasi
        if (!validateForm()) {
            return;
        }

        setIsSubmitting(true);

        try {
            // Prepare data untuk API
            const disputeData = {
                claim_text: formData.claim_text,
                reason: formData.reason,
                reporter_name: formData.reporter_name || 'Anonymous',
                reporter_email: formData.reporter_email || ''
            };

            // Tambahkan supporting evidence berdasarkan tipe
            if (buktiType === 'doi_link' && formData.supporting_doi) {
                disputeData.supporting_doi = formData.supporting_doi;
            } else if (buktiType === 'upload_pdf' && formData.supporting_file) {
                disputeData.supporting_file = formData.supporting_file;
                if (formData.supporting_url) {
                    disputeData.supporting_url = formData.supporting_url;
                }
            }

            // Call API
            const result = await createDispute(disputeData);
            
            console.log('Dispute created:', result);
            
            // Success
            setSubmitStatus('success');
            
            // Reset form
            setFormData({
                claim_text: '',
                reason: '',
                reporter_name: '',
                reporter_email: '',
                supporting_doi: '',
                supporting_url: '',
                supporting_file: null
            });
            
            // Reset file input
            const fileInput = document.getElementById('pdf_upload');
            if (fileInput) fileInput.value = null;

            // Auto hide success message after 5 seconds
            setTimeout(() => {
                setSubmitStatus(null);
            }, 5000);

        } catch (error) {
            console.error('Error submitting dispute:', error);
            setSubmitStatus('error');
            setErrorMessage(error.message || 'Gagal mengirim laporan. Silakan coba lagi.');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen bg-gradient-to-b from-blue-50 to-blue-200 font-poppins text-slate-800">
            {/* Konten utama halaman laporan */}
            <main className="container mx-auto px-4 py-10 md:py-16 max-w-4xl">
                {/* Judul Halaman */}
                <h1 className="text-2xl sm:text-3xl md:text-4xl font-bold mb-6 sm:mb-8 text-slate-800 text-center">
                    Laporkan Kesalahan Klaim
                </h1>

                {/* Success Message */}
                {submitStatus === 'success' && (
                    <div className="mb-6 bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3 animate-fade-in">
                        <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                            <h4 className="font-semibold text-green-800 mb-1 text-sm sm:text-base">Laporan Berhasil Dikirim!</h4>
                            <p className="text-xs sm:text-sm text-green-600">
                                Terima kasih atas kontribusi Anda. Tim Healthify akan meninjau laporan Anda dalam 1-3 hari kerja.
                            </p>
                        </div>
                    </div>
                )}

                {/* Error Message */}
                {(submitStatus === 'error' || errorMessage) && (
                    <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3 animate-fade-in">
                        <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                            <h4 className="font-semibold text-red-800 mb-1 text-sm sm:text-base">Terjadi Kesalahan</h4>
                            <p className="text-xs sm:text-sm text-red-600">{errorMessage || 'Gagal mengirim laporan'}</p>
                        </div>
                    </div>
                )}

                {/* Kartu Form */}
                <div className="bg-white p-4 sm:p-6 md:p-10 rounded-xl shadow-2xl border border-gray-100">
                    <form onSubmit={handleSubmit} className="space-y-4 sm:space-y-6">
                        {/* Field Klaim yang dilaporkan */}
                        <section className="space-y-3 sm:space-y-4">
                            <label htmlFor="claim_text" className="block text-base sm:text-lg font-semibold text-slate-700">
                                Klaim yang Dilaporkan <span className="text-red-500">*</span>
                            </label>
                            <textarea
                                id="claim_text"
                                name="claim_text"
                                value={formData.claim_text}
                                onChange={handleInputChange}
                                rows="4"
                                required
                                className="w-full p-3 sm:p-4 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-150 resize-none placeholder-gray-400 text-sm sm:text-base"
                                placeholder="Salin dan tempel klaim yang ingin Anda laporkan disini..."
                                disabled={isSubmitting}
                            />
                        </section>

                        {/* Field Deskripsi Kesalahan */}
                        <section className="space-y-2">
                            <label
                                htmlFor="reason"
                                className="block text-xs sm:text-sm font-poppins text-slate-600"
                            >
                                Jelaskan mengapa hasil verifikasi menurut Anda salah <span className="text-red-500">*</span>
                            </label>
                            <textarea
                                id="reason"
                                name="reason"
                                value={formData.reason}
                                onChange={handleInputChange}
                                rows="3"
                                required
                                className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition duration-150 resize-none placeholder-gray-400 text-sm"
                                placeholder="Detail alasan ketidaksesuaian..."
                                disabled={isSubmitting}
                            />
                        </section>

                        {/* Field Reporter Info (Optional) */}
                        <section className="space-y-3 sm:space-y-4">
                            <h3 className="text-base sm:text-lg font-semibold text-slate-700">Informasi Pelapor (Opsional)</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                                <div>
                                    <label htmlFor="reporter_name" className="block text-xs sm:text-sm font-poppins text-slate-600 mb-2">
                                        Nama
                                    </label>
                                    <input
                                        type="text"
                                        id="reporter_name"
                                        name="reporter_name"
                                        value={formData.reporter_name}
                                        onChange={handleInputChange}
                                        className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 transition duration-150 placeholder-gray-400 text-sm"
                                        placeholder="Nama Anda"
                                        disabled={isSubmitting}
                                    />
                                </div>
                                <div>
                                    <label htmlFor="reporter_email" className="block text-xs sm:text-sm font-poppins text-slate-600 mb-2">
                                        Email
                                    </label>
                                    <input
                                        type="email"
                                        id="reporter_email"
                                        name="reporter_email"
                                        value={formData.reporter_email}
                                        onChange={handleInputChange}
                                        className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 transition duration-150 placeholder-gray-400 text-sm"
                                        placeholder="email@example.com"
                                        disabled={isSubmitting}
                                    />
                                </div>
                            </div>
                        </section>

                        <hr className="my-4 sm:my-6 border-gray-200" />

                        {/* Field Bukti Pendukung */}
                        <section className="space-y-3 sm:space-y-4">
                            <label className="block text-base sm:text-lg font-semibold text-slate-700">
                                Bukti Pendukung <span className="text-red-500">*</span>
                            </label>

                            {/* Opsi Radio Button */}
                            <div className="flex flex-col sm:flex-row gap-3 sm:gap-6 text-xs sm:text-sm font-medium text-slate-600">
                                <label className="flex items-center space-x-2 cursor-pointer">
                                    <input
                                        type="radio"
                                        name="bukti_type"
                                        value="doi_link"
                                        checked={buktiType === 'doi_link'}
                                        onChange={() => handleBuktiTypeChange('doi_link')}
                                        className="text-blue-600 focus:ring-blue-500"
                                        disabled={isSubmitting}
                                    />
                                    <span>Link DOI</span>
                                </label>
                                <label className="flex items-center space-x-2 cursor-pointer">
                                    <input
                                        type="radio"
                                        name="bukti_type"
                                        value="upload_pdf"
                                        checked={buktiType === 'upload_pdf'}
                                        onChange={() => handleBuktiTypeChange('upload_pdf')}
                                        className="text-blue-600 focus:ring-blue-500"
                                        disabled={isSubmitting}
                                    />
                                    <span>Upload File PDF</span>
                                </label>
                            </div>

                            {/* Input Link DOI */}
                            {buktiType === 'doi_link' && (
                                <div className="space-y-2 animate-fade-in">
                                    <label htmlFor="supporting_doi" className="block text-xs sm:text-sm font-poppins text-slate-600">
                                        Link DOI <span className="text-red-500">*</span>
                                    </label>
                                    <input
                                        type="url"
                                        id="supporting_doi"
                                        name="supporting_doi"
                                        value={formData.supporting_doi}
                                        onChange={handleInputChange}
                                        className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 transition duration-150 placeholder-gray-400 text-sm"
                                        placeholder="https://doi.org/10.xxxx/xxxxx"
                                        required={buktiType === 'doi_link'}
                                        disabled={isSubmitting}
                                    />
                                    <p className="text-xs text-slate-500">Masukan Link DOI dari jurnal ilmiah yang mendukung klaim Anda</p>
                                </div>
                            )}

                            {/* Input Upload PDF */}
                            {buktiType === 'upload_pdf' && (
                                <div className="space-y-3 animate-fade-in">
                                    <div className="space-y-2">
                                        <label htmlFor="pdf_upload" className="block text-xs sm:text-sm font-poppins text-slate-600">
                                            Upload File PDF <span className="text-red-500">*</span>
                                        </label>
                                        <div className="relative">
                                            <input
                                                type="file"
                                                id="pdf_upload"
                                                accept=".pdf"
                                                onChange={handleFileChange}
                                                className="block w-full text-xs sm:text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-xs sm:file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer disabled:opacity-50"
                                                required={buktiType === 'upload_pdf' && !formData.supporting_file}
                                                disabled={isSubmitting}
                                            />
                                        </div>
                                        {formData.supporting_file && (
                                            <p className="text-xs text-green-600 flex items-center gap-2">
                                                <CheckCircle className="w-4 h-4" />
                                                File terpilih: {formData.supporting_file.name}
                                            </p>
                                        )}
                                        <p className="text-xs text-slate-500">Maksimal ukuran file: 20MB</p>
                                    </div>

                                    {/* Optional URL field */}
                                    <div className="space-y-2">
                                        <label htmlFor="supporting_url" className="block text-xs sm:text-sm font-poppins text-slate-600">
                                            Link Sumber (Opsional)
                                        </label>
                                        <input
                                            type="url"
                                            id="supporting_url"
                                            name="supporting_url"
                                            value={formData.supporting_url}
                                            onChange={handleInputChange}
                                            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 transition duration-150 placeholder-gray-400 text-sm"
                                            placeholder="https://example.com/artikel"
                                            disabled={isSubmitting}
                                        />
                                    </div>
                                </div>
                            )}
                        </section>

                        {/* Tombol Submit */}
                        <button
                            type="submit"
                            disabled={isSubmitting}
                            className="w-full bg-blue-600 text-white font-bold py-3 rounded-lg shadow-lg hover:bg-blue-700 active:bg-blue-800 transition-all duration-200 mt-6 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 text-sm sm:text-base"
                        >
                            {isSubmitting ? (
                                <>
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    <span>Mengirim Laporan...</span>
                                </>
                            ) : (
                                <>
                                    <Upload className="w-5 h-5" />
                                    <span>Kirim Laporan</span>
                                </>
                            )}
                        </button>

                        {/* Kotak Catatan */}
                        <div className="bg-yellow-50 border-l-4 border-yellow-500 p-3 sm:p-4 rounded-lg text-xs sm:text-sm text-yellow-800">
                            <p className="font-semibold mb-1">Catatan:</p>
                            <p>
                                Tim Healthify akan meninjau laporan Anda dan melakukan verifikasi terhadap bukti yang diberikan. 
                                Proses ini dapat memakan waktu <b>1-3 hari kerja</b>. Terima kasih atas kontribusi Anda dalam 
                                meningkatkan akurasi Healthify.
                            </p>
                        </div>
                    </form>
                </div>
            </main>
        </div>
    );
};

export default Report;