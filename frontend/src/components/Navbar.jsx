import React from "react";
import Logo from "../assets/Logo.png"; 

const Navbar = () => {
    return (
        <nav className="bg-blue-800 text-white p-4 shadow-md w-full">
            <div className="max-w-7xl mx-auto px-8 flex justify-between items-center font-poppins">
                {/* Logo */}
                <a 
                    href='#' 
                    className="flex items-center space-x-3"
                >
                    <img src={Logo} alt="Healthify Logo" className="h-10 w-10"/>
                    
                    <h1 className="text-xl font-bold text-white">Healthify</h1>
                </a>

                {/* Navigation Links */}
                <div className="flex items-center space-x-8">
                    <a href="#" className="text-white hover:text-cyan-300 transition-colors font-medium">
                        Beranda
                    </a>
                    <a href="#" className="text-white hover:text-cyan-300 transition-colors font-medium">
                        Dokumentasi
                    </a>
                    
                    <a
                        href="#" 
                        className="bg-blue-500 text-white px-6 py-2 rounded-md font-semibold hover:bg-blue-600 transition-colors"
                    >
                        Laporkan
                    </a>
                </div>

                {/* Language */}
                <div>
                    <a href="#" className="font-medium text-white hover:text-cyan-300 transition-colors">
                        ID / EN
                    </a>
                </div>
            </div>
        </nav>
    );
};

export default Navbar;