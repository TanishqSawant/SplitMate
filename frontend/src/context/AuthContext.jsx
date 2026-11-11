import React, { createContext, useContext, useState, useEffect } from 'react';
import { MOCK_USERS } from '../api/mockData';
import { apiClient } from '../api/client';
import { API_ENDPOINTS } from '../api/endpoints';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    const authFlag = localStorage.getItem('splitmate_is_authenticated');
    if (authFlag === 'false') return false;
    return true; // Default to true for hackathon presentation convenience
  });

  const [currentUser, setCurrentUser] = useState(() => {
    const authFlag = localStorage.getItem('splitmate_is_authenticated');
    if (authFlag === 'false') return null;
    const saved = localStorage.getItem('splitmate_auth_user');
    return saved ? JSON.parse(saved) : MOCK_USERS[0];
  });
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (currentUser && isAuthenticated) {
      localStorage.setItem('splitmate_auth_user', JSON.stringify(currentUser));
      localStorage.setItem('splitmate_is_authenticated', 'true');
    } else {
      localStorage.removeItem('splitmate_auth_user');
      localStorage.setItem('splitmate_is_authenticated', 'false');
    }
  }, [currentUser, isAuthenticated]);

  // Demo user quick-switch (essential for hackathon team demonstration)
  const switchUser = (userId) => {
    const found = MOCK_USERS.find((u) => u.id === userId);
    if (found) {
      setCurrentUser(found);
      setIsAuthenticated(true);
      localStorage.setItem('splitmate_auth_user', JSON.stringify(found));
      localStorage.setItem('splitmate_is_authenticated', 'true');
    }
  };

  const login = async (email, password) => {
    setIsLoading(true);
    try {
      if (!email?.trim() || !password?.trim()) {
        throw new Error('Please provide both email and password.');
      }

      await apiClient.request(API_ENDPOINTS.AUTH.LOGIN, {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), password: password.trim() }),
      });

      const user = MOCK_USERS.find((u) => u.email.toLowerCase() === email.trim().toLowerCase()) || {
        id: `usr_${Date.now()}`,
        name: email.split('@')[0],
        email: email.trim(),
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: `${email.split('@')[0]}-sandbox@paypal.com`,
        role: 'Team Member',
      };

      setCurrentUser(user);
      setIsAuthenticated(true);
      localStorage.setItem('splitmate_auth_user', JSON.stringify(user));
      localStorage.setItem('splitmate_is_authenticated', 'true');
      return { success: true, user };
    } catch (err) {
      return { success: false, error: err.message || 'Login failed. Please check your credentials.' };
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (userData) => {
    setIsLoading(true);
    try {
      if (!userData?.name?.trim() || !userData?.email?.trim() || !userData?.password?.trim()) {
        throw new Error('Name, email, and password are required.');
      }
      if (userData.password.length < 4) {
        throw new Error('Password must be at least 4 characters.');
      }

      await apiClient.request(API_ENDPOINTS.AUTH.REGISTER, {
        method: 'POST',
        body: JSON.stringify(userData),
      });

      const newUser = {
        id: `usr_${Date.now()}`,
        name: userData.name.trim(),
        email: userData.email.trim(),
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: userData.paypalEmail?.trim() || `${userData.email.split('@')[0]}@sandbox.paypal.com`,
        role: 'Team Member',
      };

      setCurrentUser(newUser);
      setIsAuthenticated(true);
      localStorage.setItem('splitmate_auth_user', JSON.stringify(newUser));
      localStorage.setItem('splitmate_is_authenticated', 'true');
      return { success: true, user: newUser };
    } catch (err) {
      return { success: false, error: err.message || 'Registration failed.' };
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    setCurrentUser(null);
    setIsAuthenticated(false);
    localStorage.removeItem('splitmate_auth_user');
    localStorage.setItem('splitmate_is_authenticated', 'false');
  };

  const updateProfile = (updates) => {
    setCurrentUser((prev) => ({ ...prev, ...updates }));
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isAuthenticated,
        isLoading,
        allUsers: MOCK_USERS,
        switchUser,
        login,
        register,
        logout,
        updateProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

