export const metadata = {
  title: "TradeCrew — Multi-Agent Trading Dashboard",
  description: "watsonx.data workshop — autonomous paper-trading agents",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{
        margin: 0,
        background: "#0d1117",
        color: "#e6edf3",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      }}>
        {children}
      </body>
    </html>
  );
}
