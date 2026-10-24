import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata={title:"MatchLens AI",description:"Predict. Analyze. Explain.",icons:{icon:"/icon.svg"}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
