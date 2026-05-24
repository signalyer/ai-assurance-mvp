import { render } from 'preact';
import { App } from './app';
import './shared/styles/base.css';

const root = document.getElementById('app');
if (!root) throw new Error('Missing #app root element');
render(<App />, root);
