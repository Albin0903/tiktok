import type {Metadata} from "next";
import "@fontsource/space-grotesk/latin-600.css";
import "@fontsource/space-grotesk/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-700.css";
import "./styles.css";

export const metadata: Metadata = {
  title: "Vérité Fiscale 2027",
  description: "Comparez l’impôt sur le revenu du projet de loi de finances et d’un gel du barème.",
};

export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="fr"><body>{children}</body></html>;
}
