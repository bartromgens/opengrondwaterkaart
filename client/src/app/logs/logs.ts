import { Component, ElementRef, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { Meta } from '@angular/platform-browser';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleChange, MatSlideToggleModule } from '@angular/material/slide-toggle';
import { HttpErrorResponse } from '@angular/common/http';

import { AuthService } from '../auth.service';
import { LogFileContent, LogFileInfo, LogsService } from '../logs.service';
import { SeoService } from '../seo.service';

const LINE_OPTIONS = [500, 2000, 5000, 10000];
const AUTO_REFRESH_MS = 5000;
const PREFERRED_LOG = 'management.log';

@Component({
  selector: 'app-logs',
  imports: [
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    MatSlideToggleModule,
  ],
  templateUrl: './logs.html',
  styleUrl: './logs.scss',
})
export class LogsComponent implements OnInit, OnDestroy {
  private logs = inject(LogsService);
  private auth = inject(AuthService);
  private seo = inject(SeoService);
  private meta = inject(Meta);
  private router = inject(Router);

  @ViewChild('viewer') viewer?: ElementRef<HTMLDivElement>;

  readonly lineOptions = LINE_OPTIONS;
  readonly files = signal<LogFileInfo[]>([]);
  readonly selectedFile = signal(PREFERRED_LOG);
  readonly lineCount = signal(2000);
  readonly content = signal<LogFileContent | null>(null);
  readonly lines = signal<string[]>([]);
  readonly loading = signal(true);
  readonly refreshing = signal(false);
  readonly error = signal<string | null>(null);
  readonly autoRefresh = signal(false);
  readonly username = this.auth.username;

  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private requestInFlight = false;

  ngOnInit(): void {
    this.seo.updateMetadata({
      title: 'Logs — OpenGrondWaterKaart',
      description: 'Beheerder logbestanden van OpenGrondWaterKaart.',
      path: '/logs',
    });
    this.meta.updateTag({ name: 'robots', content: 'noindex, nofollow' });
    this.loadFiles();
  }

  ngOnDestroy(): void {
    this.clearTimer();
    this.meta.removeTag('name="robots"');
  }

  onFileChange(name: string): void {
    this.selectedFile.set(name);
    this.loadContent();
  }

  onLineCountChange(lines: number): void {
    this.lineCount.set(lines);
    this.loadContent();
  }

  onAutoRefreshChange(event: MatSlideToggleChange): void {
    this.autoRefresh.set(event.checked);
    this.clearTimer();
    if (event.checked) {
      this.refreshTimer = setInterval(() => this.loadContent(true), AUTO_REFRESH_MS);
    }
  }

  refresh(): void {
    this.loadFiles(true);
  }

  formatBytes(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  formatModified(iso: string): string {
    return new Date(iso).toLocaleString('nl-NL');
  }

  lineClass(line: string): string {
    if (line.includes(' ERROR ') || line.includes(' CRITICAL ')) {
      return 'log-error';
    }
    if (line.includes(' WARNING ')) {
      return 'log-warning';
    }
    return '';
  }

  private loadFiles(silent = false): void {
    if (!silent) {
      this.loading.set(true);
    }
    this.error.set(null);
    this.logs.listFiles().subscribe({
      next: (response) => {
        this.files.set(response.files);
        const names = response.files.map((file) => file.name);
        const current = this.selectedFile();
        if (!names.includes(current)) {
          this.selectedFile.set(names.includes(PREFERRED_LOG) ? PREFERRED_LOG : (names[0] ?? ''));
        }
        if (this.selectedFile()) {
          this.loadContent();
        } else {
          this.loading.set(false);
          this.content.set(null);
          this.lines.set([]);
        }
      },
      error: (err: HttpErrorResponse) => this.handleError(err),
    });
  }

  private loadContent(silent = false): void {
    const name = this.selectedFile();
    if (!name || this.requestInFlight) {
      return;
    }
    this.requestInFlight = true;
    if (!silent) {
      this.refreshing.set(true);
    }
    this.logs.getContent(name, this.lineCount()).subscribe({
      next: (response) => {
        this.content.set(response);
        this.lines.set(response.content ? response.content.split('\n') : []);
        this.loading.set(false);
        this.refreshing.set(false);
        this.requestInFlight = false;
        this.error.set(null);
        setTimeout(() => this.scrollToBottom());
      },
      error: (err: HttpErrorResponse) => {
        this.requestInFlight = false;
        this.refreshing.set(false);
        this.handleError(err);
      },
    });
  }

  private handleError(err: HttpErrorResponse): void {
    this.loading.set(false);
    if (err.status === 403) {
      void this.router.navigateByUrl('/');
      return;
    }
    this.error.set('Kon logs niet laden.');
  }

  private scrollToBottom(): void {
    const el = this.viewer?.nativeElement;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }

  private clearTimer(): void {
    if (this.refreshTimer !== null) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
  }
}
