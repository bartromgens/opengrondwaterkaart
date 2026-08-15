import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface LogFileInfo {
  name: string;
  size: number;
  modified: string;
}

export interface LogFileList {
  files: LogFileInfo[];
}

export interface LogFileContent extends LogFileInfo {
  lines: number;
  truncated: boolean;
  content: string;
}

@Injectable({ providedIn: 'root' })
export class LogsService {
  private http = inject(HttpClient);

  listFiles(): Observable<LogFileList> {
    return this.http.get<LogFileList>('/api/admin/logs/', { withCredentials: true });
  }

  getContent(name: string, lines: number): Observable<LogFileContent> {
    const params = new HttpParams().set('lines', lines);
    return this.http.get<LogFileContent>(`/api/admin/logs/${encodeURIComponent(name)}/`, {
      params,
      withCredentials: true,
    });
  }
}
