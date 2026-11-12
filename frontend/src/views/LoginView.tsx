import React, { useState } from 'react';
import { useAuth } from '../context/useAuth';
import { AlertCircle, Eye, EyeOff, Loader2 } from 'lucide-react';
import './LoginView.css';

export const LoginView: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await login(username, password);
    } catch (err: any) {
      setError(err.message || 'Error al iniciar sesión');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-card" aria-label="Inicio de sesión de CardiNova">
        <div className="login-brand-panel">
          <div className="login-brand">
            <img className="login-isotype" src="/isotipo.svg" alt="" />
            <img className="login-wordmark" src="/wordmark.svg" alt="CardiNova" />
            <p className="login-brand-description">
              <span>CONTROL DE PROCESOS DE PRODUCCIÓN MEDIANTE VISIÓN ARTIFICIAL </span>
            </p>
          </div>
          <span className="login-brand-caption">Centro de Aprendizaje Robótica Desarrollo e
Innovación S.A.C
</span>
        </div>

        <div className="login-form-panel">
          <header className="login-heading">
            <span className="login-eyebrow">PLATAFORMA DE PRODUCCIÓN</span>
            <h1>Bienvenido</h1>
            <p>Ingresa tus credenciales para continuar.</p>
          </header>

          {error && (
            <div className="login-error" role="alert">
              <AlertCircle size={17} aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="login-form">
            <div className="login-field">
              <label htmlFor="login-username">Usuario</label>
              <input
                id="login-username"
                type="text"
                className="input-control"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Tu usuario"
                autoComplete="username"
                required
              />
            </div>

            <div className="login-field">
              <label htmlFor="login-password">Contraseña</label>
              <div className="login-password-control">
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  className="input-control"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Ingresa tu contraseña"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="login-password-toggle"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                  aria-pressed={showPassword}
                  aria-controls="login-password"
                >
                  {showPassword
                    ? <EyeOff size={19} aria-hidden="true" />
                    : <Eye size={19} aria-hidden="true" />}
                </button>
              </div>
            </div>

            <button type="submit" className="btn btn-primary login-submit" disabled={loading}>
              {loading ? <Loader2 size={18} className="animate-spin" /> : 'Ingresar al sistema'}
            </button>
          </form>

          <p className="login-notice">
            Gestión y supervisión de procesos mediante visión artificial.
          </p>
        </div>
      </section>
    </main>
  );
};
