import Hero from '../components/Hero';
import FAQSection from '../components/FAQSection';
import Sources from '../components/Sources';

const Home = () => {
  return (
    <div className="space-y-20 pb-10">
      <Hero />
      <FAQSection />
      <Sources />
    </div>
  );
};

export default Home;