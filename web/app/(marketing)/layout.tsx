import Nav from "@/components/Nav";
import Footer from "@/components/Footer";

/** Public site chrome: top nav + footer around the page content. */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <a href="#main" className="skip-link">
        Lewati ke konten utama
      </a>
      <Nav />
      <main id="main">{children}</main>
      <Footer />
    </>
  );
}
