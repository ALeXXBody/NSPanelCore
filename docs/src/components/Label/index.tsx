import React from 'react';
import styles from './styles.module.css';


// Predefined label colors
const labelColors = {
    // example to add labels
    // feature: '#28a745',
    // bug: '#d73a49',
    // feature: '#28a745',
};

// Utility function to generate random colors
const generateRandomColor = () => {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) {
        color += letters[Math.floor(Math.random() * 16)];
    }
    return color;
};

const Label = ({ value }) => {
    // Determine the color for the label
    const color = labelColors[value.toLowerCase()] || generateRandomColor();

    return (
        <span
            className={styles.label}
            style={{backgroundColor: color}}
        >
            {value.toUpperCase()}
        </span>
    );
};

export default Label;