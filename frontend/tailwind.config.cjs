module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { 
    extend: {
        fontFamily: {
            poppins: ['Poppins', 'sans-serif'],
        },
        colors: {
            secondary50: '#E8F5E9',
            neutral600: '#4B5563',
            secondary900: '#0D47A1',
            neutral700: '#374151',
            neutral800: '#1F2937',
            primary100: '#C8E6C9',
            secondary500: '#2196F3',
            primary50: '#E8F5E9',
            neutral50: '#F9FAFB',
            neutral900: '#111827',
            info: '#0288D1',
            success: '#2E7D32',
            warning: '#FFB300'
        }
    },
},
plugins: [],
};