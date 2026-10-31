import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "./index.css";

// One shared cache for the whole app. Created outside any component so it's made once.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 60 * 1000, // data stays fresh for 1 hour (it changes once a day)
      retry: 2,                  // Render's free instance can fail the first request while waking
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);