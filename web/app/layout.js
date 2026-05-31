import "./globals.css";

export const metadata = {
  title: "FixFinance",
  description: "AI personal-finance consultant",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="header">
          <div className="brand">Fix<span>Finance</span></div>
          <div className="muted" style={{ fontSize: 12 }}>preliminary advisory — not regulated advice</div>
        </div>
        {children}
      </body>
    </html>
  );
}
