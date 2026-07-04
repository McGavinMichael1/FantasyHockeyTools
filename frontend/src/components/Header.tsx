'use client';

import styles from './Header.module.css';

interface HeaderProps {
  activeTab: 'pickups' | 'cooling';
  onTabChange: (tab: 'pickups' | 'cooling') => void;
  dataAge?: string;
}

export default function Header({ activeTab, onTabChange, dataAge }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <span className={styles.logo}>FH</span>
        <span className={styles.title}>Fantasy Hockey</span>
      </div>

      <nav className={styles.nav}>
        <button
          className={`${styles.tab} ${activeTab === 'pickups' ? styles.active : ''}`}
          onClick={() => onTabChange('pickups')}
        >
          <span className={styles.tabIcon}>▲</span>
          Pickups
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'cooling' ? styles.active : ''}`}
          onClick={() => onTabChange('cooling')}
        >
          <span className={styles.tabIcon}>▼</span>
          Cooling
        </button>
      </nav>

      <div className={styles.meta}>
        {dataAge && (
          <span className={styles.dataAge}>
            Data: {dataAge}
          </span>
        )}
      </div>
    </header>
  );
}
