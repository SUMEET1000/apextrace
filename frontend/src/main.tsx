import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { startLoader } from './landing/loader';
import { QueryProvider } from './lib/router';
import { ThemeProvider } from './lib/theme';
import './styles/global.css';
import './styles/legacy.css';

startLoader();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryProvider>
        <App />
      </QueryProvider>
    </ThemeProvider>
  </StrictMode>,
);
