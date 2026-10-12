import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 8501, host: '127.0.0.1' },
  preview: { port: 8501, host: '127.0.0.1' },
});
