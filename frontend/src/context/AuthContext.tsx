import React, { useState, useEffect, useCallback } from 'react';
import type { User } from '../types';
import { loginApi, getMeApi } from '../api/endpoints';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem('cardinova_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem('cardinova_token');
  });
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const logout = useCallback(() => {
    localStorage.removeItem('cardinova_token');
    localStorage.removeItem('cardinova_user');
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    async function verifyAuth() {
      if (token) {
        try {
          const freshUser = await getMeApi();
          setUser(freshUser);
          localStorage.setItem('cardinova_user', JSON.stringify(freshUser));
        } catch {
          logout();
        }
      }
      setIsLoading(false);
    }

    verifyAuth();

    const handleExpired = () => logout();
    window.addEventListener('cardinova_auth_expired', handleExpired);
    return () => window.removeEventListener('cardinova_auth_expired', handleExpired);
  }, [token, logout]);

  const login = async (username: string, password: string) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);

    const res = await loginApi(formData);
    localStorage.setItem('cardinova_token', res.access_token);
    localStorage.setItem('cardinova_user', JSON.stringify(res.user));
    setToken(res.access_token);
    setUser(res.user);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token && !!user,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
