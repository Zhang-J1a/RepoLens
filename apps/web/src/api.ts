import type { Job, TaskInput } from './types';

export async function api<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(
    path,
    payload === undefined
      ? undefined
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.error === 'string'
        ? data.error
        : typeof data.detail === 'string'
          ? data.detail
          : `请求失败 (${response.status})`,
    );
  return data as T;
}
export const submitTask = (payload: TaskInput) => api<Job>('/api/tasks', payload);
export const short = (value?: string | null) => value?.slice(0, 10) || '-';
export const localDate = (value: string) =>
  new Date(value).toLocaleString('zh-CN', { hour12: false });
