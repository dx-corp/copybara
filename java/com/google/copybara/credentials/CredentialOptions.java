/*
 * Copyright (C) 2023 Google LLC.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.google.copybara.credentials;

import com.beust.jcommander.Parameter;
import com.google.copybara.Option;
import java.nio.file.Path;
import javax.annotation.Nullable;

/**
 * Flags related to credentials
 */
public class CredentialOptions implements Option {

  @Parameter(
      names = "--credential-file",
      description = "Location of a TOML file for reading credentials")
  @Nullable public Path credentialFile = null;
}
