import { useContext } from 'react';
import ExpenseContext from './ExpenseContext';

export const useExpenses = () => useContext(ExpenseContext);

