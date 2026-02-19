export const mailProviderOptions = [
  { label: 'Moemail', value: 'moemail' },
  { label: 'DuckMail', value: 'duckmail' },
  { label: 'Freemail', value: 'freemail' },
  { label: 'GPTMail', value: 'gptmail' },
] as const

export type TempMailProvider = typeof mailProviderOptions[number]['value']

export const defaultMailProvider: TempMailProvider = 'moemail'
